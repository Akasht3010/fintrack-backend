from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.schemas.admin import HealthResponse, StatsResponse
from app.services import admin_service
from app.utils.admin_auth import require_admin_key

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


@router.get("/health", response_model=HealthResponse)
async def admin_health(db: Session = Depends(get_db)):
    """Deeper than the public /health: includes a live DB ping and process uptime."""
    return admin_service.get_health(db)


@router.get("/stats", response_model=StatsResponse)
async def admin_stats(db: Session = Depends(get_db)):
    """Aggregate counts for the monitoring dashboard — never per-user detail."""
    return admin_service.get_stats(db)
