from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.schemas.account import AccountBalanceUpdate, AccountCreate, AccountResponse, AccountUpdate, NetWorthSummary
from app.services.account_service import AccountInUseError, AccountService, compute_balances
from app.utils.auth import get_current_user
from app.utils.timezone import now_ist, to_ist_naive

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

@router.get("", response_model=list[AccountResponse])
def list_accounts(
    include_archived: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List the authenticated user's accounts (active only, unless include_archived=true), with live balances."""
    accounts = AccountService.list_visible(db, current_user.id, include_archived)
    balances = compute_balances(db, accounts)
    return [AccountService.to_response(db, a, balances[a.id]) for a in accounts]

@router.get("/net-worth", response_model=NetWorthSummary)
def get_net_worth(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Net worth = sum of asset account balances minus credit card balances owed."""
    return AccountService.net_worth(db, current_user.id)

@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create an account with a starting balance (0 if you're tracking from here on)."""
    account = AccountService.create(
        db, current_user.id, payload.name, payload.type, payload.currency, payload.opening_balance,
        institution=payload.institution, last4=payload.last4, card_last4=payload.card_last4
    )
    return AccountService.to_response(db, account)

@router.patch("/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: int,
    payload: AccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Rename, correct the opening balance, or archive/unarchive an account."""
    account = AccountService.get_own(db, current_user.id, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    updated = AccountService.update(
        db, account, payload.name, payload.opening_balance, payload.is_archived,
        fields_set=payload.model_fields_set, institution=payload.institution,
        last4=payload.last4, card_last4=payload.card_last4
    )
    return AccountService.to_response(db, updated)

@router.post("/{account_id}/balance", response_model=AccountResponse)
def set_account_balance(
    account_id: int,
    payload: AccountBalanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reconcile: set the balance to what the bank / UPI app shows. Later
    transactions are applied on top of it."""
    account = AccountService.get_own(db, current_user.id, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    at = to_ist_naive(payload.as_of) if payload.as_of else now_ist()
    updated = AccountService.set_balance(db, account, payload.balance, at)
    return AccountService.to_response(db, updated)

@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an account. 409s if any transaction still references it — archive it instead to keep history."""
    account = AccountService.get_own(db, current_user.id, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    try:
        AccountService.delete(db, account)
    except AccountInUseError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account still has transactions linked to it — archive it instead, or reassign those transactions first"
        )
    return {"message": "Account deleted"}
