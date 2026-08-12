from pydantic import BaseModel
from typing import List, Optional


class SmsMessage(BaseModel):
    address: Optional[str] = None
    body: Optional[str] = None
    date: int  # epoch milliseconds, as read from the device


class SmsSyncRequest(BaseModel):
    messages: List[SmsMessage]


class SmsSyncResponse(BaseModel):
    imported: int
    skipped_duplicate: int
    skipped_unparsed: int
