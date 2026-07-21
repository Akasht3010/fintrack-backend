from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.config.database import get_db
from app.schemas.transaction import TransactionCreate, TransactionResponse, TransactionList
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the authenticated user's transactions with pagination"""
    query = db.query(Transaction).filter(Transaction.user_id == current_user.id)

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
