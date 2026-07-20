from google.auth.oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
import os
import json
from datetime import datetime, timedelta

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

class GmailService:
    def __init__(self, credentials_json: str, token_json: str = None):
        """
        credentials_json: Path to Google OAuth credentials JSON
        token_json: Serialized user token (from DB)
        """
        self.credentials_json = credentials_json
        self.token_json = token_json

    def get_auth_url(self, redirect_uri: str) -> tuple[str, str]:
        """
        Generate OAuth URL for user to click
        Returns: (auth_url, state)
        """
        flow = Flow.from_client_secrets_file(
            self.credentials_json,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
        auth_url, state = flow.authorization_url(
            access_type='offline',
            prompt='consent'
        )
        return auth_url, state

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = None):
        """
        Exchange auth code for refresh token
        Returns: refresh_token, access_token
        """
        flow = Flow.from_client_secrets_file(
            self.credentials_json,
            scopes=SCOPES,
            redirect_uri=redirect_uri,
            state=state
        )
        flow.fetch_token(code=code)
        
        credentials = flow.credentials
        return credentials.refresh_token, credentials.token

    def get_gmail_service(self, refresh_token: str):
        """
        Build Gmail service from refresh token
        """
        credentials = Credentials.from_authorized_user_info(
            {
                'refresh_token': refresh_token,
                'type': 'authorized_user',
                'client_id': os.getenv('GOOGLE_CLIENT_ID'),
                'client_secret': os.getenv('GOOGLE_CLIENT_SECRET')
            },
            scopes=SCOPES
        )
        return build('gmail', 'v1', credentials=credentials)

    def fetch_emails(self, refresh_token: str, query: str = 'is:unread', max_results: int = 10):
        """
        Fetch emails from Gmail
        """
        try:
            service = self.get_gmail_service(refresh_token)
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            emails = []
            
            for msg in messages:
                email = self.get_email_details(service, msg['id'])
                if email:
                    emails.append(email)
            
            return emails
        except HttpError as error:
            print(f'An error occurred: {error}')
            return []

    def get_email_details(self, service, message_id: str) -> dict:
        """
        Get full details of an email
        """
        try:
            message = service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            headers = message['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), '')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
            date_str = next((h['value'] for h in headers if h['name'] == 'Date'), '')
            
            # Get email body
            body = self.get_email_body(message)
            
            return {
                'id': message_id,
                'subject': subject,
                'from': sender,
                'date': date_str,
                'body': body,
                'snippet': message['snippet']
            }
        except Exception as e:
            print(f'Error getting email details: {e}')
            return None

    def get_email_body(self, message: dict) -> str:
        """
        Extract email body text
        """
        try:
            if 'parts' in message['payload']:
                parts = message['payload']['parts']
                text = ''
                for part in parts:
                    if part['mimeType'] == 'text/plain':
                        if 'data' in part['body']:
                            text += base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                return text
            else:
                if 'data' in message['payload']['body']:
                    return base64.urlsafe_b64decode(message['payload']['body']['data']).decode('utf-8')
        except Exception as e:
            print(f'Error extracting email body: {e}')
        
        return message.get('snippet', '')

    def search_bank_emails(self, refresh_token: str, days: int = 30) -> list:
        """
        Search for bank transaction emails from last N days
        """
        date_limit = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')
        
        # Common bank email patterns
        query = f'after:{date_limit} (from:noreply@hdfc OR from:alerts@icicibank OR from:alerts@axisbank OR from:noreply@sbi OR from:alert@kotak)'
        
        return self.fetch_emails(refresh_token, query=query, max_results=50)
