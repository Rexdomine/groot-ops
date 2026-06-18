from __future__ import annotations

import logging
import os
import re
import urllib.parse
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import (
    SESSION_COOKIE_NAME,
    SESSION_DAYS,
    AuthError,
    AuthUser,
    DatabaseAuthBackend,
)
from .config_loader import load_client_config
from .db import check_database_ready
from .main_daily_summary import run_daily_summary
from .main_process_leads import process_leads
from .owner_notifications import send_owner_setup_confirmation_email as send_setup_confirmation_email
from .repository_factory import create_lead_repository
from .models import ClientConfig
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
logger = logging.getLogger(__name__)


PROTECTED_UI_PREFIXES = ("/setup", "/dashboard", "/clients/")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_protected_ui_path(path: str) -> bool:
    return path in {"/setup", "/dashboard"} or path.startswith(PROTECTED_UI_PREFIXES)


def _is_auth_path(path: str) -> bool:
    return path in {"/login", "/signup", "/logout"}


def _safe_next_path(next_path: str | None) -> str:
    candidate = (next_path or "/setup").strip() or "/setup"
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/setup"
    if candidate.startswith("/login") or candidate.startswith("/signup") or candidate.startswith("/logout"):
        return "/setup"
    return candidate


def _login_redirect_for(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(url=f"/login?next={urllib.parse.quote(next_path, safe='')}", status_code=303)


def _validate_signup_form(full_name: str, email: str, password: str) -> list[str]:
    errors: list[str] = []
    if len(full_name.strip()) < 2:
        errors.append("Enter your full name.")
    if not EMAIL_RE.match(email.strip()):
        errors.append("Enter a valid email address.")
    if len(password) < 12:
        errors.append("Password must be at least 12 characters.")
    return errors


def _session_cookie_secure(request: Request) -> bool:
    configured = os.getenv("GROOT_OPS_SESSION_COOKIE_SECURE", "").strip().lower()
    if configured in {"1", "true", "yes", "on"}:
        return True
    if configured in {"0", "false", "no", "off"}:
        return False
    public_base_url = os.getenv("GROOT_OPS_PUBLIC_BASE_URL", "").strip().lower()
    return request.url.scheme == "https" or public_base_url.startswith("https://") or bool(os.getenv("VERCEL"))


def _set_session_cookie(response: RedirectResponse, token: str, *, request: Request) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=_session_cookie_secure(request),
        samesite="lax",
    )


def _clear_session_cookie(response: RedirectResponse, *, request: Request) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        httponly=True,
        secure=_session_cookie_secure(request),
        samesite="lax",
    )


def _template_context(request: Request, **values: Any) -> dict[str, Any]:
    context = {"current_user": getattr(request.state, "current_user", None)}
    context.update(values)
    return context


def _public_base_url(request: Request) -> str:
    configured = os.getenv("GROOT_OPS_PUBLIC_BASE_URL", "").strip().rstrip("/")
    return configured or str(request.base_url).rstrip("/")


def _private_dashboard_url(request: Request, client_id: str) -> str:
    quoted_client_id = urllib.parse.quote(client_id)
    return f"{_public_base_url(request)}/clients/{quoted_client_id}/dashboard"


def _setup_values_from_config(config: ClientConfig) -> dict[str, str]:
    column_mapping = config.column_mapping or {}
    return {
        "client_id": config.client_id,
        "business_name": config.business_name,
        "agent_name": config.agent_name,
        "agent_email": config.agent_email,
        "agent_phone": config.agent_phone,
        "timezone": config.timezone,
        "spreadsheet_url": config.spreadsheet_id,
        "leads_sheet": config.leads_sheet,
        "activity_log_sheet": config.activity_log_sheet,
        "column_name": column_mapping.get("name", ""),
        "column_phone": column_mapping.get("phone", ""),
        "column_email": column_mapping.get("email", ""),
        "column_budget": column_mapping.get("budget", ""),
        "column_desired_location": column_mapping.get("desired_location", ""),
        "column_timeline": column_mapping.get("timeline", ""),
        "column_message": column_mapping.get("message", ""),
        "owner_channel": config.owner_notification_channel,
        "owner_destination": config.owner_notification_destination,
        "daily_summary_time": config.daily_summary_time,
        "process_leads_frequency": config.process_leads_frequency,
        "hot_timeline_days": str(config.hot_timeline_days),
        "warm_timeline_days": str(config.warm_timeline_days),
        "stale_after_days": str(config.stale_after_days),
        "voice": config.voice,
        "max_draft_chars": str(config.max_draft_chars),
        "required_disclaimer": config.required_disclaimer,
    }


def create_app(*, auth_backend: Any | None = None) -> FastAPI:
    app = FastAPI(title="Groot Ops Demo UI", version="0.1.0")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    auth_service: Any = auth_backend or DatabaseAuthBackend()

    @app.middleware("http")
    async def attach_user_and_protect_routes(request: Request, call_next: Any) -> Any:
        request.state.current_user = None
        session_token = request.cookies.get(SESSION_COOKIE_NAME, "")
        if session_token:
            request.state.current_user = auth_service.get_user_for_session(session_token)
        if _is_protected_ui_path(request.url.path) and request.state.current_user is None:
            return _login_redirect_for(request)
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "groot-ops-ui"}

    @app.get("/ready")
    def ready() -> JSONResponse:
        database = check_database_ready()
        status_code = 200 if database.ok else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ready" if database.ok else "not_ready",
                "service": "groot-ops-ui",
                "database": {
                    "ok": database.ok,
                    "status": database.status,
                },
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> Any:
        configs = list_demo_configs()
        return templates.TemplateResponse(request, "home.html", _template_context(request, configs=configs))

    @app.get("/signup", response_class=HTMLResponse)
    def signup_form(request: Request) -> Any:
        return templates.TemplateResponse(
            request,
            "signup.html",
            _template_context(request, errors=[], values={}, configs=list_demo_configs()),
        )

    @app.post("/signup", response_class=HTMLResponse)
    def signup_submit(
        request: Request,
        full_name: str = Form(""),
        email: str = Form(""),
        password: str = Form(""),
    ) -> Any:
        errors = _validate_signup_form(full_name, email, password)
        values = {"full_name": full_name, "email": email}
        if errors:
            return templates.TemplateResponse(
                request,
                "signup.html",
                _template_context(request, errors=errors, values=values, configs=list_demo_configs()),
                status_code=400,
            )
        try:
            user = auth_service.create_user(email=email, password=password, full_name=full_name)
            if hasattr(auth_service, "create_session"):
                session = auth_service.create_session(
                    user_id=user.id,
                    user_agent=request.headers.get("user-agent", ""),
                    ip_address=request.client.host if request.client else "",
                )
            else:
                # Test backends can create the session as part of authentication instead of exposing create_session.
                session = auth_service.authenticate_user(
                    email=email,
                    password=password,
                    user_agent=request.headers.get("user-agent", ""),
                    ip_address=request.client.host if request.client else "",
                )
        except AuthError as exc:
            return templates.TemplateResponse(
                request,
                "signup.html",
                _template_context(request, errors=[str(exc)], values=values, configs=list_demo_configs()),
                status_code=400,
            )
        except Exception as exc:
            logger.exception("signup session creation failed: %s", exc.__class__.__name__)
            return templates.TemplateResponse(
                request,
                "signup.html",
                _template_context(
                    request,
                    errors=["We could not create your account right now. Please try again."],
                    values=values,
                    configs=list_demo_configs(),
                ),
                status_code=500,
            )
        response = RedirectResponse(url="/setup", status_code=303)
        _set_session_cookie(response, session.token, request=request)
        return response

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next_path: str = Query("/setup", alias="next"), logged_out: str = "") -> Any:
        return templates.TemplateResponse(
            request,
            "login.html",
            _template_context(
                request,
                errors=[],
                values={},
                next_path=_safe_next_path(next_path),
                logged_out=bool(logged_out),
                configs=list_demo_configs(),
            ),
        )

    @app.post("/login", response_class=HTMLResponse)
    def login_submit(
        request: Request,
        email: str = Form(""),
        password: str = Form(""),
        next_path: str = Query("/setup", alias="next"),
    ) -> Any:
        redirect_path = _safe_next_path(next_path)
        try:
            session = auth_service.authenticate_user(
                email=email,
                password=password,
                user_agent=request.headers.get("user-agent", ""),
                ip_address=request.client.host if request.client else "",
            )
        except AuthError as exc:
            return templates.TemplateResponse(
                request,
                "login.html",
                _template_context(
                    request,
                    errors=[str(exc)],
                    values={"email": email},
                    next_path=redirect_path,
                    logged_out=False,
                    configs=list_demo_configs(),
                ),
                status_code=401,
            )
        response = RedirectResponse(url=redirect_path, status_code=303)
        _set_session_cookie(response, session.token, request=request)
        return response

    @app.post("/logout")
    def logout(request: Request) -> RedirectResponse:
        token = request.cookies.get(SESSION_COOKIE_NAME, "")
        if token:
            auth_service.revoke_session(token)
        response = RedirectResponse(url="/login?logged_out=1", status_code=303)
        _clear_session_cookie(response, request=request)
        return response

    @app.get("/setup", response_class=HTMLResponse)
    def setup(request: Request, client_id: str = "") -> Any:
        configs = list_demo_configs()
        values: dict[str, str] = {}
        editing_client_id = client_id.strip()
        if editing_client_id:
            config_path = safe_config_path(editing_client_id)
            if not config_path.exists():
                raise HTTPException(status_code=404, detail="Demo client config not found")
            values = _setup_values_from_config(load_client_config(config_path))
        return templates.TemplateResponse(
            request,
            "setup.html",
            _template_context(request, values=values, checks=[], configs=configs, editing=bool(editing_client_id)),
        )

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
            _template_context(
                request,
                values=form,
                client_id=data["client_id"],
                config_path=str(config_path),
                dashboard_url=dashboard_url,
                email_status=email_status,
                checks=checks,
                saved=True,
                configs=list_demo_configs(),
            ),
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
            _template_context(
                request,
                config=config,
                config_path=str(config_path),
                checks=checks,
                leads=leads,
                lead_error=lead_error,
                cards=cards,
                summary=summary,
                preview=preview,
                ready_checks=ready_checks,
                total_checks=len(checks),
                dashboard_path=dashboard_path,
                configs=list_demo_configs(),
            ),
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
