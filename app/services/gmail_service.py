from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
import os
from datetime import datetime, timedelta

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def _client_config():
    return {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


class GmailService:
    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """Generate the Gmail OAuth consent URL"""
        flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri)
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            prompt='consent',
            state=state
        )
        return auth_url

    def exchange_code_for_token(self, code: str, redirect_uri: str) -> str:
        """Exchange an auth code for a refresh token"""
        flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri)
        flow.fetch_token(code=code)
        return flow.credentials.refresh_token

    def get_gmail_service(self, refresh_token: str):
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv('GOOGLE_CLIENT_ID'),
            client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
            scopes=SCOPES
        )
        return build('gmail', 'v1', credentials=credentials)

    def fetch_emails(self, refresh_token: str, query: str = 'is:unread', max_results: int = 10):
        # Let HttpError propagate — a real API failure (e.g. Gmail API not
        # enabled, revoked access) must surface as an error, not look
        # identical to "no matching emails found".
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

    def get_email_details(self, service, message_id: str) -> dict:
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
        """Search for bank transaction emails from the last N days"""
        date_limit = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')

        # Keyword-based rather than guessing specific bank sender addresses —
        # far more likely to actually match real alert emails regardless of
        # which bank sent them. False positives are filtered out downstream
        # by the amount parser (an email with no parseable amount is skipped).
        keywords = (
            'debited OR credited OR "transaction alert" OR "payment alert" '
            'OR "account alert" OR "has been debited" OR "has been credited" '
            'OR "spent on your" OR "you paid" OR "money received"'
        )
        query = f'after:{date_limit} ({keywords})'

        return self.fetch_emails(refresh_token, query=query, max_results=50)
