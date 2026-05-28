from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import ClientConfig


def _resolve_path(config_path: Path, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((config_path.parent / path).resolve())


def load_client_config(path: str | Path) -> ClientConfig:
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle) or {}

    repository = raw.get("repository") or {}
    scoring = raw.get("scoring") or {}
    messaging = raw.get("messaging") or {}
    summary = raw.get("summary") or {}
    notifications = raw.get("notifications") or {}
    schedule = raw.get("schedule") or {}

    required = ["client_id", "business_name", "agent_name", "agent_phone", "agent_email"]
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError(f"Missing required client config fields: {', '.join(missing)}")
    repository_type = repository.get("type", "csv")
    if repository_type not in {"csv", "google_sheets"}:
        raise ValueError("repository.type must be one of: csv, google_sheets")

    leads_csv = ""
    activity_log_csv = ""
    spreadsheet_id = ""
    leads_sheet = "Leads"
    activity_log_sheet = "Activity Log"
    credentials_env = ""
    service_account_file = ""

    if repository_type == "csv":
        if not repository.get("leads_csv"):
            raise ValueError("Missing repository.leads_csv")
        leads_csv = _resolve_path(config_path, repository["leads_csv"])
        activity_log_csv = _resolve_path(config_path, repository.get("activity_log_csv", "../data/activity_log.csv"))
    else:
        spreadsheet_id = str(repository.get("spreadsheet_id") or "")
        if not spreadsheet_id or spreadsheet_id.startswith("REPLACE_"):
            raise ValueError("Missing repository.spreadsheet_id for google_sheets repository")
        leads_sheet = str(repository.get("leads_sheet") or leads_sheet)
        activity_log_sheet = str(repository.get("activity_log_sheet") or activity_log_sheet)
        credentials_env = str(repository.get("credentials_env") or "")
        service_account_file_raw = str(repository.get("service_account_file") or "")
        service_account_file = (
            _resolve_path(config_path, service_account_file_raw)
            if service_account_file_raw
            and not service_account_file_raw.startswith("$")
            and not service_account_file_raw.startswith("~")
            else service_account_file_raw
        )
        if not credentials_env and not service_account_file:
            raise ValueError(
                "Google Sheets repository requires repository.credentials_env or repository.service_account_file"
            )

    return ClientConfig(
        client_id=raw["client_id"],
        business_name=raw["business_name"],
        agent_name=raw["agent_name"],
        agent_phone=str(raw["agent_phone"]),
        agent_email=raw["agent_email"],
        timezone=raw.get("timezone", "UTC"),
        repository_type=repository_type,
        leads_csv=leads_csv,
        activity_log_csv=activity_log_csv,
        spreadsheet_id=spreadsheet_id,
        leads_sheet=leads_sheet,
        activity_log_sheet=activity_log_sheet,
        credentials_env=credentials_env,
        service_account_file=service_account_file,
        hot_timeline_days=int(scoring.get("hot_timeline_days", 14)),
        warm_timeline_days=int(scoring.get("warm_timeline_days", 60)),
        stale_after_days=int(summary.get("stale_after_days", scoring.get("stale_after_days", 7))),
        max_draft_chars=int(messaging.get("max_draft_chars", 700)),
        required_disclaimer=messaging.get("required_disclaimer", "Reply STOP to opt out."),
        voice=messaging.get("voice", "friendly, concise, professional"),
        owner_notification_channel=str(notifications.get("owner_channel", "telegram")),
        owner_notification_destination=str(notifications.get("owner_destination", "")),
        daily_summary_time=str(schedule.get("daily_summary_time", "08:30")),
        process_leads_frequency=str(schedule.get("process_leads_frequency", "every_2h_weekdays")),
        automation_status=str(schedule.get("automation_status", "demo_manual")),
        column_mapping={str(key): str(value) for key, value in (repository.get("column_mapping") or {}).items() if value},
    )
