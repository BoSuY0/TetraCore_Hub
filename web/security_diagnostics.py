from fastapi import APIRouter
from config import get_settings
from core.config_diagnostics import run_security_config_diagnostics

router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/config-diagnostics")
async def security_config_diagnostics():
    settings = get_settings()
    return run_security_config_diagnostics(settings)
