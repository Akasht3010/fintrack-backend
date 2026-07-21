from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.schemas.budget import BudgetCreate, BudgetUpdate, BudgetResponse
from app.services.budget_service import BudgetService, DuplicateBudgetError
from app.models.user import User
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/budgets", tags=["budgets"])

@router.post("", response_model=BudgetResponse)
async def create_budget(
    budget: BudgetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a budget for a category over the current week/month. 409s if one already covers this category."""
    try:
        created = BudgetService.create_budget(
            db, current_user.id, budget.category, budget.limit_amount, budget.period
        )
    except DuplicateBudgetError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A budget for '{budget.category}' already covers the current period"
        )
    return BudgetService.to_response(db, created)

@router.get("", response_model=list[BudgetResponse])
async def list_budgets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List the authenticated user's budgets active in the current period, with live spend computed from transactions."""
    budgets = BudgetService.list_active_budgets(db, current_user.id)
    return [BudgetService.to_response(db, b) for b in budgets]

@router.patch("/{budget_id}", response_model=BudgetResponse)
async def update_budget(
    budget_id: str,
    update: BudgetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a budget's limit amount"""
    budget = BudgetService.get_budget(db, current_user.id, budget_id)
    if not budget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")

    updated = BudgetService.update_limit(db, budget, update.limit_amount)
    return BudgetService.to_response(db, updated)

@router.delete("/{budget_id}")
async def delete_budget(
    budget_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a budget"""
    budget = BudgetService.get_budget(db, current_user.id, budget_id)
    if not budget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")

    BudgetService.delete_budget(db, budget)
    return {"message": "Budget deleted"}
