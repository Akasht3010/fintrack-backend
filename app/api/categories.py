from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryResponse, CategoryUpdate
from app.services.category_service import CategoryInUseError, CategoryService, DuplicateCategoryError
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/categories", tags=["categories"])

@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    type: str | None = Query(default=None, pattern="^(expense|income|both)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Built-in default categories plus this user's own custom ones.
    Pass ?type=expense or ?type=income to also include "both" categories
    (transfer, other) but exclude the other type's — omit it for everything."""
    return CategoryService.list_visible(db, current_user.id, type)

@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a custom category. 409s if the name collides with a default or one of the user's own."""
    try:
        return CategoryService.create(db, current_user.id, payload.name, payload.icon, payload.type)
    except DuplicateCategoryError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A category with this name already exists")

@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Rename, re-icon, or retype a custom category (owner-only; default categories 404). Renaming cascades onto existing transactions/budgets."""
    category = CategoryService.get_own(db, current_user.id, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    try:
        return CategoryService.update(db, category, payload.name, payload.icon, payload.type)
    except DuplicateCategoryError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A category with this name already exists")

@router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a custom category. 409s if any transaction or budget still references it."""
    category = CategoryService.get_own(db, current_user.id, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    try:
        CategoryService.delete(db, category)
    except CategoryInUseError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This category is still used by existing transactions or budgets"
        )
    return {"message": "Category deleted"}
