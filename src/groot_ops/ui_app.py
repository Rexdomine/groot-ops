from __future__ import annotations

import os
import urllib.parse
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
from .owner_notifications import send_owner_setup_confirmation_email as send_setup_confirmation_email
from .repository_factory import create_lead_repository
from .ui_config_service import (
    build_client_config_dict,
    list_demo_configs,
    load_latest_or_sample,
    safe_config_path,
    set_automation_status,
    validate_setup,
    write_client_config,
)

PACKAGE_DIR = Path(__file__).resolve().parent


PROTECTED_UI_PREFIXES = ("/setup", "/dashboard", "/clients/")


def _dashboard_token() -> str:
    return os.getenv("GROOT_OPS_DASHBOARD_TOKEN", "").strip()


def _is_protected_ui_path(path: str) -> bool:
    return path in {"/setup", "/dashboard"} or path.startswith(PROTECTED_UI_PREFIXES)


def _request_has_valid_dashboard_token(request: Request, expected_token: str) -> bool:
    supplied_token = (
        request.query_params.get("token")
        or request.headers.get("X-Groot-Ops-Dashboard-Token")
        or request.cookies.get("groot_ops_dashboard_token")
        or ""
    ).strip()
    return bool(supplied_token and supplied_token == expected_token)


def _unauthorized_dashboard_response() -> HTMLResponse:
    return HTMLResponse(
        """
        <!doctype html>
        <title>Groot Ops dashboard access required</title>
        <main style="font-family: system-ui, sans-serif; max-width: 640px; margin: 10vh auto; padding: 2rem;">
          <h1>Dashboard access required</h1>
          <p>This pilot dashboard is protected. Open the private dashboard link that includes the access token, or ask Groot Ops support for a fresh link.</p>
        </main>
        """,
        status_code=401,
    )


def _public_base_url(request: Request) -> str:
    configured = os.getenv("GROOT_OPS_PUBLIC_BASE_URL", "").strip().rstrip("/")
    return configured or str(request.base_url).rstrip("/")


def _private_dashboard_url(request: Request, client_id: str) -> str:
    quoted_client_id = urllib.parse.quote(client_id)
    url = f"{_public_base_url(request)}/clients/{quoted_client_id}/dashboard"
    dashboard_token = _dashboard_token()
    if dashboard_token:
        url = f"{url}?token={urllib.parse.quote(dashboard_token)}"
    return url


def create_app() -> FastAPI:
    app = FastAPI(title="Groot Ops Demo UI", version="0.1.0")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))

    @app.middleware("http")
    async def protect_dashboard_routes(request: Request, call_next: Any) -> Any:
        expected_token = _dashboard_token()
        if expected_token and _is_protected_ui_path(request.url.path):
            if not _request_has_valid_dashboard_token(request, expected_token):
                return _unauthorized_dashboard_response()
            response = await call_next(request)
            if request.query_params.get("token") == expected_token:
                response.set_cookie(
                    "groot_ops_dashboard_token",
                    expected_token,
                    httponly=True,
                    secure=request.url.scheme == "https",
                    samesite="lax",
                )
            return response
        return await call_next(request)

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
        dashboard_url = _private_dashboard_url(request, data["client_id"])
        email_status = ""
        try:
            result = send_setup_confirmation_email(config, dashboard_url=dashboard_url)
            email_status = f"Confirmation email sent to {result.get('to', config.agent_email)}."
        except Exception as exc:
            email_status = f"Confirmation email not sent yet: {exc}"
        return templates.TemplateResponse(
            request,
            "setup.html",
            {
                "values": form,
                "client_id": data["client_id"],
                "config_path": str(config_path),
                "dashboard_url": dashboard_url,
                "email_status": email_status,
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

    @app.post("/clients/{client_id}/activate", response_class=HTMLResponse)
    def activate_automation(request: Request, client_id: str) -> Any:
        config_path = safe_config_path(client_id)
        if not config_path.exists():
            raise HTTPException(status_code=404, detail="Demo client config not found")
        set_automation_status(config_path, "active")
        return dashboard(request, client_id, summary="Pilot automation marked active in the saved config. Enable the operator scheduler/Hermes cron separately for recurring production runs.")

    return app


app = create_app()
