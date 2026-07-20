from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.services.gmail_service import GmailService
from app.services.user_service import UserService
from pydantic import BaseModel
from app.models.transaction import Transaction
import os
from datetime import datetime

router = APIRouter(prefix="/api/gmail", tags=["gmail"])

gmail_service = GmailService(credentials_json="credentials.json")

class GmailConnectRequest(BaseModel):
    code: str
    redirect_uri: str

class GmailAuthUrl(BaseModel):
    auth_url: str
    state: str

@router.get("/auth-url")
async def get_gmail_auth_url(redirect_uri: str = Query(...)):
    """Get Gmail OAuth URL"""
    auth_url, state = gmail_service.get_auth_url(redirect_uri)
    return {
        "auth_url": auth_url,
        "state": state
    }

@router.post("/connect")
async def connect_gmail(
    request: GmailConnectRequest,
    user_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """Exchange auth code for refresh token and save to user"""
    try:
        refresh_token, access_token = gmail_service.exchange_code_for_token(
            request.code,
            request.redirect_uri
        )
        
        # Update user with refresh token
        user = UserService.update_gmail_token(db, user_id, refresh_token)
        
        return {
            "success": True,
            "message": "Gmail connected successfully",
            "user": {
                "id": user.id,
                "email": user.email,
                "gmail_connected": user.gmail_connected
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to connect Gmail: {str(e)}"
        )

@router.post("/sync")
async def sync_gmail_emails(
    user_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """Fetch and parse bank emails from Gmail"""
    user = UserService.get_user_by_id(db, user_id)
    
    if not user or not user.gmail_connected or not user.gmail_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gmail not connected"
        )
    
    try:
        # Fetch bank emails
        emails = gmail_service.search_bank_emails(user.gmail_refresh_token)
        
        synced_count = 0
        for email in emails:
            # TODO: Parse email and create transaction
            # For now, just count
            synced_count += 1
        
        return {
            "success": True,
            "synced": synced_count,
            "message": f"Synced {synced_count} emails"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync Gmail: {str(e)}"
        )

@router.get("/emails")
async def list_gmail_emails(
    user_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """List bank emails from Gmail (for debugging)"""
    user = UserService.get_user_by_id(db, user_id)
    
    if not user or not user.gmail_connected or not user.gmail_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gmail not connected"
        )
    
    try:
        emails = gmail_service.search_bank_emails(user.gmail_refresh_token)
        return {
            "count": len(emails),
            "emails": emails
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
