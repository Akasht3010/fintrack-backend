from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
import os
import html as html_lib
import re
from typing import AbstractSet, Optional
import httpx
from datetime import datetime, timedelta

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def _html_to_text(markup: str) -> str:
    markup = re.sub(r'(?is)<(script|style)\b.*?</\1>', ' ', markup)
    markup = re.sub(r'(?i)<br\s*/?>|</(p|div|tr|li|h\d)>', '\n', markup)
    markup = re.sub(r'<[^>]+>', ' ', markup)
    text = html_lib.unescape(markup)
    text = re.sub(r'[ \t\xa0]+', ' ', text)
    return re.sub(r'\s*\n\s*', '\n', text).strip()


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

    def revoke_token(self, refresh_token: str) -> None:
        """Best-effort: tell Google to revoke this grant so it no longer shows under the user's connected apps."""
        httpx.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": refresh_token},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=10
        )

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

    def fetch_emails(
        self, refresh_token: str, query: str = 'is:unread', max_results: int = 10,
        skip_ids: AbstractSet[str] = frozenset()
    ):
        # Let HttpError propagate — a real API failure (e.g. Gmail API not
        # enabled, revoked access) must surface as an error, not look
        # identical to "no matching emails found".
        service = self.get_gmail_service(refresh_token)

        # Gmail pages its results (at most 500 ids a page, often far fewer);
        # reading only the first page silently dropped everything past it.
        ids: list[str] = []
        page_token = None
        while len(ids) < max_results:
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=min(500, max_results - len(ids)),
                pageToken=page_token
            ).execute()
            ids.extend(msg['id'] for msg in results.get('messages', []))
            page_token = results.get('nextPageToken')
            if not page_token:
                break

        emails = []
        for message_id in ids:
            if message_id in skip_ids:
                continue
            email = self.get_email_details(service, message_id)
            if email:
                emails.append(email)

        return emails

    def get_email_details(self, service, message_id: str) -> Optional[dict]:
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
        """Plain-text body; falls back to the HTML part with tags stripped.
        Many bank alerts are HTML-only, and parts can nest (multipart/
        alternative inside multipart/mixed) — reading only top-level
        text/plain parts left the parser with nothing but the snippet."""
        plain: list[str] = []
        html: list[str] = []

        def walk(part: dict) -> None:
            data = part.get('body', {}).get('data')
            mime = part.get('mimeType', '')
            if data and mime in ('text/plain', 'text/html'):
                try:
                    decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
                except Exception:
                    decoded = ''
                (plain if mime == 'text/plain' else html).append(decoded)
            for child in part.get('parts', []) or []:
                walk(child)

        walk(message.get('payload', {}))
        if plain:
            return '\n'.join(plain)
        if html:
            return _html_to_text('\n'.join(html))
        return message.get('snippet', '')

    def search_bank_emails(
        self, refresh_token: str, days: int = 30, max_results: int = 500,
        skip_ids: AbstractSet[str] = frozenset()
    ) -> list:
        """Search for bank transaction emails from the last N days"""
        date_limit = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')

        # Keyword-based rather than guessing specific bank sender addresses —
        # far more likely to actually match real alert emails regardless of
        # which bank sent them. Deliberately excludes merchant / UPI-app
        # receipt phrasings ("you paid", "payment successful", "money
        # received") — those fire for the same purchase the bank already
        # alerted on, so including them just multiplied every transaction.
        # Remaining false positives are dropped downstream by the parser
        # (no parseable amount / statement wording) and by the sync's
        # same-amount-within-10-minutes dedup.
        keywords = (
            '"debited from" OR "credited to" OR "has been debited" '
            'OR "has been credited" OR "transaction alert" OR "debit alert" '
            'OR "credit alert" OR "account alert" OR "is debited" OR "is credited" '
            'OR "debited by" OR "debited with" OR "credited with" '
            'OR "spent on" OR "spent using" OR "used for a transaction"'
        )
        query = f'after:{date_limit} ({keywords})'

        return self.fetch_emails(refresh_token, query=query, max_results=max_results, skip_ids=skip_ids)
