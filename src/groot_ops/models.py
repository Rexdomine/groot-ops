from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ClientConfig:
    client_id: str
    business_name: str
    agent_name: str
    agent_phone: str
    agent_email: str
    timezone: str
    repository_type: str = "csv"
    leads_csv: str = ""
    activity_log_csv: str = ""
    spreadsheet_id: str = ""
    leads_sheet: str = "Leads"
    activity_log_sheet: str = "Activity Log"
    credentials_env: str = ""
    service_account_file: str = ""
    hot_timeline_days: int = 14
    warm_timeline_days: int = 60
    stale_after_days: int = 7
    max_draft_chars: int = 700
    required_disclaimer: str = "Reply STOP to opt out."
    voice: str = "friendly, concise, professional"


@dataclass
class Lead:
    lead_id: str
    created_at: str = ""
    name: str = ""
    email: str = ""
    phone: str = ""
    source: str = ""
    budget: str = ""
    desired_location: str = ""
    timeline: str = ""
    property_type: str = ""
    message: str = ""
    last_contacted_at: str = ""
    follow_up_due_at: str = ""
    status: str = "new"
    approval_status: str = ""
    draft_message: str = ""
    recommended_action: str = ""
    lead_score: str = ""
    lead_temperature: str = ""
    errors: str = ""
    updated_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "Lead":
        known = {f.name for f in cls.__dataclass_fields__.values() if f.name != "extra"}
        values = {key: (row.get(key) or "") for key in known}
        values["extra"] = {k: v for k, v in row.items() if k not in known}
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "lead_id": self.lead_id,
            "created_at": self.created_at,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "source": self.source,
            "budget": self.budget,
            "desired_location": self.desired_location,
            "timeline": self.timeline,
            "property_type": self.property_type,
            "message": self.message,
            "last_contacted_at": self.last_contacted_at,
            "follow_up_due_at": self.follow_up_due_at,
            "status": self.status,
            "approval_status": self.approval_status,
            "draft_message": self.draft_message,
            "recommended_action": self.recommended_action,
            "lead_score": self.lead_score,
            "lead_temperature": self.lead_temperature,
            "errors": self.errors,
            "updated_at": self.updated_at,
        }
        data.update(self.extra)
        return data


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
