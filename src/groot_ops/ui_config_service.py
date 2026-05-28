from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

from .config_loader import load_client_config
from .csv_repository import DEFAULT_FIELDS
from .models import ClientConfig
from .repository_factory import create_lead_repository


REQUIRED_LEAD_COLUMNS = [
    "lead_id",
    "name",
    "email",
    "phone",
    "budget",
    "desired_location",
    "timeline",
    "status",
]


@dataclass(frozen=True)
class SetupCheck:
    label: str
    status: str
    message: str

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"


def parse_spreadsheet_id(value: str) -> str:
    """Extract a Google Sheets spreadsheet ID from a URL or return the raw ID."""
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if "/spreadsheets/d/" in cleaned:
        match = re.search(r"/spreadsheets/d/([^/#?]+)", cleaned)
        return match.group(1) if match else cleaned
    parsed = urlparse(cleaned)
    if parsed.query:
        query_id = parse_qs(parsed.query).get("id", [""])[0]
        if query_id:
            return query_id
    return cleaned


def slugify_client_id(business_name: str, agent_name: str = "") -> str:
    base = f"{business_name} {agent_name}".strip() or "demo_client"
    slug = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
    return slug[:48] or "demo_client"


def _int_from_form(form: dict[str, str], key: str, default: int) -> int:
    try:
        return int((form.get(key) or default))
    except (TypeError, ValueError):
        return default


def build_client_config_dict(form: dict[str, str]) -> dict[str, Any]:
    business_name = (form.get("business_name") or "Demo Realty Group").strip()
    agent_name = (form.get("agent_name") or "Demo Agent").strip()
    spreadsheet_id = parse_spreadsheet_id(form.get("spreadsheet_url") or form.get("spreadsheet_id") or "")
    client_id = (form.get("client_id") or slugify_client_id(business_name, agent_name)).strip()
    return {
        "client_id": client_id,
        "business_name": business_name,
        "agent_name": agent_name,
        "agent_phone": (form.get("agent_phone") or "").strip(),
        "agent_email": (form.get("agent_email") or "").strip(),
        "timezone": (form.get("timezone") or "America/New_York").strip(),
        "repository": {
            "type": "google_sheets",
            "spreadsheet_id": spreadsheet_id,
            "leads_sheet": (form.get("leads_sheet") or "Leads").strip(),
            "activity_log_sheet": (form.get("activity_log_sheet") or "Activity Log").strip(),
            "credentials_env": "MATON_API_KEY",
        },
        "scoring": {
            "hot_timeline_days": _int_from_form(form, "hot_timeline_days", 14),
            "warm_timeline_days": _int_from_form(form, "warm_timeline_days", 60),
            "stale_after_days": _int_from_form(form, "stale_after_days", 7),
        },
        "messaging": {
            "max_draft_chars": _int_from_form(form, "max_draft_chars", 700),
            "required_disclaimer": (form.get("required_disclaimer") or "Reply STOP to opt out.").strip(),
            "voice": (form.get("voice") or "friendly, concise, professional").strip(),
        },
        "summary": {"stale_after_days": _int_from_form(form, "stale_after_days", 7)},
        "notifications": {
            "owner_channel": (form.get("owner_channel") or "telegram").strip(),
            "owner_destination": (form.get("owner_destination") or "").strip(),
        },
        "schedule": {
            "daily_summary_time": (form.get("daily_summary_time") or "08:30").strip(),
            "process_leads_frequency": (form.get("process_leads_frequency") or "every_2h_weekdays").strip(),
            "automation_status": "demo_manual",
        },
    }


def demo_config_dir() -> Path:
    configured = os.environ.get("GROOT_OPS_DEMO_CONFIG_DIR")
    if configured:
        return Path(configured)
    if os.environ.get("VERCEL"):
        return Path("/tmp/groot-ops-demo-configs")
    return Path("configs/demo_clients")


def safe_config_path(client_id: str, base_dir: Path | None = None) -> Path:
    base = base_dir or demo_config_dir()
    slug = slugify_client_id(client_id)
    path = (base / f"{slug}.yaml").resolve()
    base_resolved = base.resolve()
    if base_resolved not in path.parents and path != base_resolved:
        raise ValueError("Unsafe client config path")
    return path


def write_client_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def list_demo_configs(base_dir: Path | None = None) -> list[Path]:
    base = base_dir or demo_config_dir()
    if not base.exists():
        return []
    return sorted(base.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True)


def validate_setup(config: ClientConfig) -> list[SetupCheck]:
    checks: list[SetupCheck] = []
    checks.append(SetupCheck("Business profile", "ok", f"{config.business_name} / {config.agent_name}"))
    if config.repository_type != "google_sheets":
        checks.append(SetupCheck("Lead source", "warn", "Demo UI is optimized for Google Sheets pilots."))
        return checks
    if config.spreadsheet_id:
        checks.append(SetupCheck("Google Sheet", "ok", "Spreadsheet ID is configured."))
    else:
        checks.append(SetupCheck("Google Sheet", "error", "Paste a Google Sheet URL or spreadsheet ID."))
    if config.credentials_env and os.environ.get(config.credentials_env):
        checks.append(SetupCheck("Google access", "ok", f"Secure access is available through {config.credentials_env}."))
    else:
        checks.append(SetupCheck("Google access", "warn", f"{config.credentials_env or 'Google credentials'} is not configured in this environment yet."))
    try:
        leads = create_lead_repository(config).list_leads()
    except Exception as exc:  # network/credential/sheet issues become client-friendly checks
        checks.append(SetupCheck("Sheet validation", "warn", f"Could not read leads yet: {exc}"))
        return checks
    checks.append(SetupCheck("Lead rows", "ok" if leads else "warn", f"Read {len(leads)} lead row(s)."))
    if leads:
        present = set(leads[0].to_dict().keys())
    else:
        present = set(DEFAULT_FIELDS)
    missing = [column for column in REQUIRED_LEAD_COLUMNS if column not in present]
    if missing:
        checks.append(SetupCheck("Required columns", "warn", "Missing: " + ", ".join(missing)))
    else:
        checks.append(SetupCheck("Required columns", "ok", "Core lead columns are available."))
    return checks


def load_latest_or_sample() -> tuple[Path | None, ClientConfig | None]:
    configs = list_demo_configs()
    if configs:
        return configs[0], load_client_config(configs[0])
    sample = Path("configs/sample_realtor.yaml")
    if sample.exists():
        return sample, load_client_config(sample)
    return None, None
