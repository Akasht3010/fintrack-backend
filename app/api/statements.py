from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.schemas.statement import MAX_STATEMENT_BYTES, StatementImportResponse
from app.services.account_service import AccountService
from app.services.statement_parser import StatementFormatError, parse_hdfc_statement
from app.services.statement_service import StatementAccountMismatch, import_statement
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/statements", tags=["statements"])


@router.post("/import", response_model=StatementImportResponse)
def import_bank_statement(
    account_id: int = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Import an HDFC account statement (Delimited text or .xls) into one
    of the user's bank accounts. Rows already in the app (from alerts or
    manual entry) are matched rather than duplicated, missing ones are
    added, and the closing balance becomes the account's balance.
    Re-uploading the same or an overlapping statement is safe."""
    account = AccountService.get_own(db, current_user.id, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if account.type != "bank":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Statements can be imported into a debit card / bank account")

    content = file.file.read(MAX_STATEMENT_BYTES + 1)
    if len(content) > MAX_STATEMENT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Statement file is too large (max 5 MB)")

    try:
        statement = parse_hdfc_statement(content, file.filename or "")
    except StatementFormatError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    try:
        return import_statement(db, current_user.id, account, statement)
    except StatementAccountMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This statement is for account ending {exc.statement_digits}, not {account.name} (••{exc.account_digits})"
        )
