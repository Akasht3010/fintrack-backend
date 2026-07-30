from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryResponse, CategoryUpdate
from app.services.category_service import CategoryInUseError, CategoryService, DuplicateCategoryError
from app.utils.auth import get_current_user

router = APIRouter(prefix="/api/categories", tags=["categories"])

@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Built-in default categories plus this user's own custom ones."""
    return CategoryService.list_visible(db, current_user.id)

@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a custom category. 409s if the name collides with a default or one of the user's own."""
    try:
        return CategoryService.create(db, current_user.id, payload.name, payload.icon)
    except DuplicateCategoryError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A category with this name already exists")

@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str,
    payload: CategoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Rename or re-icon a custom category (owner-only; default categories 404). Renaming cascades onto existing transactions/budgets."""
    category = CategoryService.get_own(db, current_user.id, category_id)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    try:
        return CategoryService.update(db, category, payload.name, payload.icon)
    except DuplicateCategoryError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A category with this name already exists")

@router.delete("/{category_id}")
async def delete_category(
    category_id: str,
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
