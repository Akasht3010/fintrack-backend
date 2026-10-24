from pydantic import BaseModel, Field
from typing import List, Optional

# Bounds on what a single authenticated request can make the server do —
# every message costs a couple of queries and a commit. The app reads at
# most 500 inbox messages per sync (useSmsSync's INBOX_READ_LIMIT) and
# trims bodies to MAX_SMS_BODY_LENGTH before sending.
MAX_SMS_PER_SYNC = 500
MAX_SMS_BODY_LENGTH = 2000
# 2100-01-01 in epoch ms; anything past datetime's range would otherwise
# raise in fromtimestamp() and surface as a 500 instead of a 422.
MAX_SMS_DATE_MS = 4_102_444_800_000


class SmsMessage(BaseModel):
    address: Optional[str] = Field(default=None, max_length=64)
    body: Optional[str] = Field(default=None, max_length=MAX_SMS_BODY_LENGTH)
    date: int = Field(gt=0, le=MAX_SMS_DATE_MS)  # epoch milliseconds, as read from the device


class SmsSyncRequest(BaseModel):
    messages: List[SmsMessage] = Field(max_length=MAX_SMS_PER_SYNC)


class SmsSyncResponse(BaseModel):
    imported: int
    skipped_duplicate: int
    skipped_unparsed: int
