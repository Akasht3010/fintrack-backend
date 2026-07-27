import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Query as SAQuery, Session
from sqlalchemy import desc, or_
from app.config.database import get_db
from app.schemas.transaction import TransactionCreate, TransactionUpdate, TransactionResponse, TransactionList
from app.models.transaction import Transaction
from app.models.user import User
from app.utils.auth import get_current_user

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
        query = query.filter(Transaction.date >= date_from)
    if date_to:
        query = query.filter(Transaction.date <= date_to)
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
    db_transaction = Transaction(
        user_id=current_user.id,
        amount=transaction.amount,
        currency=transaction.currency,
        type=transaction.type,
        category=transaction.category,
        merchant=transaction.merchant,
        description=transaction.description,
        date=transaction.date,
        source=transaction.source,
        raw_text=transaction.raw_text,
        is_recurring=transaction.is_recurring
    )
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
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

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date", "Type", "Amount", "Currency", "Category", "Merchant", "Description", "Source", "Recurring"])
    for t in transactions:
        writer.writerow([
            t.date.isoformat(),
            t.type,
            t.amount,
            t.currency,
            t.category,
            t.merchant,
            t.description,
            t.source,
            "yes" if t.is_recurring else "no"
        ])
    buffer.seek(0)

    filename = f"fintrack-transactions-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
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
    transaction_id: str,
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
    for field, value in updates.items():
        setattr(transaction, field, value)

    db.commit()
    db.refresh(transaction)
    return transaction

@router.delete("/{transaction_id}")
async def delete_transaction(
    transaction_id: str,
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
    db.delete(transaction)
    db.commit()
    return {"message": "Transaction deleted"}
