"""Security diagnostics API endpoints for TetraCore Hub.

Provides an endpoint to run configuration security checks and return a structured report.
"""

import importlib

from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/config-diagnostics")
async def security_config_diagnostics():
    """Run security configuration diagnostics and return the report.

    Returns:
        dict: Structured report with keys like 'environment', 'status', and 'issues'.
    """
    try:
        config = importlib.import_module("config")
        diagnostics = importlib.import_module("core.config_diagnostics")
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Diagnostics import failed: {exc}"
        ) from exc

    settings = config.get_settings()
    return diagnostics.run_security_config_diagnostics(settings)
