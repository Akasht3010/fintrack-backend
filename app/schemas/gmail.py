from pydantic import BaseModel


class GmailDisconnectResponse(BaseModel):
    gmail_connected: bool


class GmailSyncResponse(BaseModel):
    imported: int
    skipped_duplicate: int
    skipped_unparsed: int
