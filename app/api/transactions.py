from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from app.config.database import get_db
from app.schemas.transaction import TransactionCreate, TransactionUpdate, TransactionResponse, TransactionList
from app.models.transaction import Transaction
from app.models.user import User
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

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
