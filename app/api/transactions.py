import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Query as SAQuery, Session
from sqlalchemy import desc, or_
from sqlalchemy.exc import IntegrityError
from app.config.database import get_db
from app.schemas.transaction import TransactionCreate, TransactionUpdate, TransactionResponse, TransactionList
from app.models.transaction import Transaction
from app.models.user import User
from app.services.account_service import AccountService
from app.services.budget_service import BudgetService
from app.services.category_service import CategoryService
from app.utils.auth import get_current_user
from app.utils.timezone import now_ist, to_ist_naive

def _ensure_category_exists(db: Session, user_id: int, category: str) -> None:
    if not CategoryService.name_exists(db, user_id, category):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown category '{category}'")

_FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

def _csv_safe(value: str) -> str:
    """Neutralizes CSV/formula injection: a cell starting with =, +, -, @,
    tab, or CR is interpreted as a formula by Excel/Sheets when opened. Most
    merchant/description text is bounded by the extraction pattern that
    produced it, but at least one (VPA_NAMED_PATTERN) captures an unbounded
    character set, so this guards every string cell regardless of source
    rather than trusting upstream validation."""
    if value and value[0] in _FORMULA_INJECTION_PREFIXES:
        return "'" + value
    return value

def _ensure_account_owned(db: Session, user_id: int, account_id: Optional[int], currency: Optional[str] = None) -> None:
    if account_id is None:
        return
    account = AccountService.get_own(db, user_id, account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown account '{account_id}'")
    # compute_balance sums a linked account's transactions in the account's
    # own currency without converting — a mismatched transaction currency
    # would silently corrupt that account's balance rather than erroring here.
    if currency is not None and currency != account.currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transaction currency '{currency}' doesn't match account '{account.name}' (currency '{account.currency}')"
        )

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

def _apply_filters(
    query: SAQuery,
    category: Optional[str],
    q: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    min_amount: Optional[float],
    max_amount: Optional[float],
    source: Optional[str] = None,
    type: Optional[str] = None
) -> SAQuery:
    if category and category != "all":
        query = query.filter(Transaction.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Transaction.merchant.ilike(like), Transaction.description.ilike(like)))
    if date_from:
        query = query.filter(Transaction.date >= to_ist_naive(date_from))
    if date_to:
        query = query.filter(Transaction.date <= to_ist_naive(date_to))
    if min_amount is not None:
        query = query.filter(Transaction.amount >= min_amount)
    if max_amount is not None:
        query = query.filter(Transaction.amount <= max_amount)
    if source and source != "all":
        query = query.filter(Transaction.source == source)
    if type and type != "all":
        query = query.filter(Transaction.type == type)
    return query

@router.post("", response_model=TransactionResponse)
async def create_transaction(
    transaction: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new transaction for the authenticated user"""
    _ensure_category_exists(db, current_user.id, transaction.category)
    _ensure_account_owned(db, current_user.id, transaction.account_id, transaction.currency)

    # The `date` column is naive IST (same convention as the Gmail/SMS sync
    # endpoints), but the client sends an offset-aware ISO string
    # (`new Date().toISOString()`). Handing that aware value straight to
    # the DB driver leaves the UTC-vs-local conversion up to the DB
    # session's own timezone setting instead of doing it explicitly here —
    # exactly the kind of implicit conversion that silently corrupts the
    # stored instant if that setting is ever anything other than what's
    # expected.
    transaction_date = to_ist_naive(transaction.date)

    db_transaction = Transaction(
        user_id=current_user.id,
        account_id=transaction.account_id,
        amount=transaction.amount,
        currency=transaction.currency,
        type=transaction.type,
        category=transaction.category,
        merchant=transaction.merchant,
        description=transaction.description,
        date=transaction_date,
        # Forced server-side rather than trusting the client's `source` —
        # the gmail/sms sync paths construct Transaction rows directly and
        # never go through this endpoint, so anything arriving here is by
        # definition manual. Without this, a client could label a
        # hand-entered transaction "gmail"/"aa" and impersonate a
        # higher-trust import.
        source="manual",
        raw_text=transaction.raw_text,
        is_recurring=transaction.is_recurring
    )
    db.add(db_transaction)
    try:
        db.commit()
    except IntegrityError:
        # Same (user_id, raw_text) dedup index the Gmail/SMS sync endpoints
        # rely on — a direct API call can hit it too (raw_text is
        # client-settable), so it needs the same graceful handling rather
        # than surfacing as an unhandled 500.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A transaction with this raw_text already exists for this account"
        )
    db.refresh(db_transaction)
    BudgetService.sync_for_categories(db, current_user.id, db_transaction.category)
    return db_transaction

@router.get("", response_model=TransactionList)
async def list_transactions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    category: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search merchant or description"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the authenticated user's transactions, paginated and optionally filtered"""
    query = db.query(Transaction).filter(Transaction.user_id == current_user.id)
    query = _apply_filters(query, category, q, date_from, date_to, min_amount, max_amount)

    total = query.count()

    transactions = query.order_by(desc(Transaction.date)).offset(
        (page - 1) * limit
    ).limit(limit).all()

    return {
        "transactions": transactions,
        "total": total,
        "page": page,
        "limit": limit
    }

@router.get("/export")
async def export_transactions(
    category: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    source: Optional[str] = Query(None, description="manual, gmail, sms, or aa"),
    type: Optional[str] = Query(None, description="debit or credit"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Export the authenticated user's transactions (optionally filtered) as CSV"""
    query = db.query(Transaction).filter(Transaction.user_id == current_user.id)
    query = _apply_filters(query, category, q, date_from, date_to, min_amount, max_amount, source, type)
    transactions = query.order_by(desc(Transaction.date)).all()

    account_names = {a.id: a.name for a in AccountService.list_visible(db, current_user.id, include_archived=True)}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date", "Type", "Amount", "Currency", "Category", "Merchant", "Description", "Source", "Account", "Recurring"])
    for t in transactions:
        writer.writerow([
            t.date.strftime("%d/%m/%Y %H:%M"),
            t.type,
            t.amount,
            t.currency,
            _csv_safe(t.category),
            _csv_safe(t.merchant),
            _csv_safe(t.description),
            t.source,
            _csv_safe(account_names.get(t.account_id, "")),
            "yes" if t.is_recurring else "no"
        ])
    buffer.seek(0)

    filename = f"fintrack-transactions-{now_ist().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific transaction owned by the authenticated user"""
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.user_id == current_user.id
    ).first()
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    return transaction

@router.patch("/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: int,
    update: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a transaction's amount/category/merchant/description. Owned-only."""
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.user_id == current_user.id
    ).first()
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )

    updates = update.model_dump(exclude_unset=True)
    if "category" in updates:
        _ensure_category_exists(db, current_user.id, updates["category"])
    if "account_id" in updates or "currency" in updates:
        effective_account_id = updates.get("account_id", transaction.account_id)
        effective_currency = updates.get("currency", transaction.currency)
        _ensure_account_owned(db, current_user.id, effective_account_id, effective_currency)

    # Editing amount/currency/type/date/category can all move the budgeted
    # total — and a category change affects both the old and new category's
    # budgets — so capture the pre-edit category before overwriting it.
    previous_category = transaction.category

    for field, value in updates.items():
        setattr(transaction, field, value)

    db.commit()
    db.refresh(transaction)
    BudgetService.sync_for_categories(db, current_user.id, {previous_category, transaction.category})
    return transaction

@router.delete("/{transaction_id}")
async def delete_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a transaction owned by the authenticated user"""
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.user_id == current_user.id
    ).first()
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    removed_category = transaction.category
    db.delete(transaction)
    db.commit()
    BudgetService.sync_for_categories(db, current_user.id, removed_category)
    return {"message": "Transaction deleted"}
