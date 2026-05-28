from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config_loader import load_client_config
from .main_daily_summary import run_daily_summary
from .main_process_leads import process_leads
from .repository_factory import create_lead_repository
from .ui_config_service import (
    build_client_config_dict,
    list_demo_configs,
    load_latest_or_sample,
    safe_config_path,
    validate_setup,
    write_client_config,
)

PACKAGE_DIR = Path(__file__).resolve().parent

def create_app() -> FastAPI:
    app = FastAPI(title="Groot Ops Demo UI", version="0.1.0")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "groot-ops-ui"}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> Any:
        configs = list_demo_configs()
        return templates.TemplateResponse(request, "home.html", {"configs": configs})

    @app.get("/setup", response_class=HTMLResponse)
    def setup(request: Request) -> Any:
        configs = list_demo_configs()
        return templates.TemplateResponse(request, "setup.html", {"values": {}, "checks": [], "configs": configs})

    @app.get("/dashboard")
    def latest_dashboard() -> RedirectResponse:
        config_path, _config = load_latest_or_sample()
        if config_path is None:
            return RedirectResponse(url="/setup")
        return RedirectResponse(url=f"/clients/{config_path.stem}/dashboard")

    @app.post("/setup", response_class=HTMLResponse)
    async def save_setup(request: Request) -> Any:
        form = {key: str(value) for key, value in (await request.form()).items()}
        data = build_client_config_dict(form)
        config_path = safe_config_path(data["client_id"])
        write_client_config(config_path, data)
        config = load_client_config(config_path)
        checks = validate_setup(config)
        return templates.TemplateResponse(
            request,
            "setup.html",
            {
                "values": form,
                "client_id": data["client_id"],
                "config_path": str(config_path),
                "checks": checks,
                "saved": True,
                "configs": list_demo_configs(),
            },
        )

    @app.get("/clients/{client_id}/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request, client_id: str, summary: str = "", preview: str = "") -> Any:
        config_path = safe_config_path(client_id)
        if not config_path.exists():
            raise HTTPException(status_code=404, detail="Demo client config not found")
        config = load_client_config(config_path)
        checks = validate_setup(config)
        leads = []
        lead_error = ""
        try:
            leads = create_lead_repository(config).list_leads()[:12]
        except Exception as exc:
            lead_error = str(exc)
        cards = {
            "new": sum(1 for lead in leads if (lead.status or "new").lower() == "new"),
            "hot": sum(1 for lead in leads if (lead.lead_temperature or "").lower() == "hot"),
            "needs_approval": sum(1 for lead in leads if "approval" in (lead.approval_status or "").lower()),
            "stale": sum(1 for lead in leads if (lead.recommended_action or "").lower().find("stale") >= 0),
        }
        ready_checks = sum(1 for check in checks if check.status == "ok")
        dashboard_path = f"/clients/{config.client_id}/dashboard"
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "config": config,
                "config_path": str(config_path),
                "checks": checks,
                "leads": leads,
                "lead_error": lead_error,
                "cards": cards,
                "summary": summary,
                "preview": preview,
                "ready_checks": ready_checks,
                "total_checks": len(checks),
                "dashboard_path": dashboard_path,
                "configs": list_demo_configs(),
            },
        )

    @app.post("/clients/{client_id}/preview-summary", response_class=HTMLResponse)
    def preview_summary(request: Request, client_id: str) -> Any:
        config_path = safe_config_path(client_id)
        if not config_path.exists():
            raise HTTPException(status_code=404, detail="Demo client config not found")
        try:
            buffer = StringIO()
            with redirect_stdout(buffer):
                output = run_daily_summary(str(config_path))
            summary = output or buffer.getvalue()
        except Exception as exc:
            summary = f"Preview could not run yet: {exc}"
        return dashboard(request, client_id, summary=summary)

    @app.post("/clients/{client_id}/preview-leads", response_class=HTMLResponse)
    def preview_leads(request: Request, client_id: str, limit: int = Form(3)) -> Any:
        config_path = safe_config_path(client_id)
        if not config_path.exists():
            raise HTTPException(status_code=404, detail="Demo client config not found")
        try:
            buffer = StringIO()
            with redirect_stdout(buffer):
                process_leads(str(config_path), dry_run=True, limit=max(1, min(limit, 10)))
            preview = buffer.getvalue()
        except Exception as exc:
            preview = f"Lead preview could not run yet: {exc}"
        return dashboard(request, client_id, preview=preview)

    return app


app = create_app()
