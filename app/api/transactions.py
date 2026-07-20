from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.config.database import get_db
from app.schemas.transaction import TransactionCreate, TransactionResponse, TransactionList
from app.models.transaction import Transaction
from pydantic import BaseModel
from datetime import datetime
from typing import Literal

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

@router.post("", response_model=TransactionResponse)
async def create_transaction(
    transaction: TransactionCreate,
    db: Session = Depends(get_db)
):
    """Create a new transaction"""
    db_transaction = Transaction(
        user_id=transaction.user_id,
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
    user_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get user's transactions with pagination"""
    query = db.query(Transaction).filter(Transaction.user_id == user_id)
    
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
async def get_transaction(transaction_id: str, db: Session = Depends(get_db)):
    """Get a specific transaction"""
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    return transaction

@router.delete("/{transaction_id}")
async def delete_transaction(transaction_id: str, db: Session = Depends(get_db)):
    """Delete a transaction"""
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    db.delete(transaction)
    db.commit()
    return {"message": "Transaction deleted"}
