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

    required = ["client_id", "business_name", "agent_name", "agent_phone", "agent_email"]
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError(f"Missing required client config fields: {', '.join(missing)}")
    if repository.get("type", "csv") != "csv":
        raise ValueError("Phase 1 MVP supports repository.type=csv only")
    if not repository.get("leads_csv"):
        raise ValueError("Missing repository.leads_csv")

    return ClientConfig(
        client_id=raw["client_id"],
        business_name=raw["business_name"],
        agent_name=raw["agent_name"],
        agent_phone=str(raw["agent_phone"]),
        agent_email=raw["agent_email"],
        timezone=raw.get("timezone", "UTC"),
        leads_csv=_resolve_path(config_path, repository["leads_csv"]),
        activity_log_csv=_resolve_path(config_path, repository.get("activity_log_csv", "../data/activity_log.csv")),
        hot_timeline_days=int(scoring.get("hot_timeline_days", 14)),
        warm_timeline_days=int(scoring.get("warm_timeline_days", 60)),
        stale_after_days=int(summary.get("stale_after_days", scoring.get("stale_after_days", 7))),
        max_draft_chars=int(messaging.get("max_draft_chars", 700)),
        required_disclaimer=messaging.get("required_disclaimer", "Reply STOP to opt out."),
        voice=messaging.get("voice", "friendly, concise, professional"),
    )
