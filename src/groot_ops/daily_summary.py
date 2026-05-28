from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .models import ClientConfig, Lead


@dataclass(frozen=True)
class DailySummary:
    new_leads: list[Lead]
    hot_leads: list[Lead]
    follow_ups_due: list[Lead]
    pending_approvals: list[Lead]
    stale_leads: list[Lead]
    errors: list[Lead]


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_daily_summary(leads: list[Lead], config: ClientConfig, now: datetime | None = None) -> DailySummary:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    follow_ups_due: list[Lead] = []
    stale: list[Lead] = []
    for lead in leads:
        due_at = _parse_dt(lead.follow_up_due_at)
        if due_at and due_at.replace(tzinfo=due_at.tzinfo or timezone.utc) <= now:
            follow_ups_due.append(lead)
        last_activity = _parse_dt(lead.last_contacted_at) or _parse_dt(lead.created_at)
        if last_activity:
            age_days = (now - last_activity.replace(tzinfo=last_activity.tzinfo or timezone.utc)).days
            if age_days >= config.stale_after_days and lead.status not in {"closed", "lost"}:
                stale.append(lead)

    return DailySummary(
        new_leads=[lead for lead in leads if lead.status == "new"],
        hot_leads=[lead for lead in leads if lead.lead_temperature == "hot"],
        follow_ups_due=follow_ups_due,
        pending_approvals=[lead for lead in leads if lead.approval_status == "needs_approval"],
        stale_leads=stale,
        errors=[lead for lead in leads if bool(lead.errors)],
    )


def format_daily_summary(summary: DailySummary) -> str:
    def line(label: str, items: list[Lead]) -> str:
        ids = ", ".join(f"{lead.lead_id} ({lead.name or 'Unnamed'})" for lead in items) or "none"
        return f"- {label}: {len(items)} — {ids}"

    return "\n".join(
        [
            "Groot Ops Daily Summary",
            line("New leads", summary.new_leads),
            line("Hot leads", summary.hot_leads),
            line("Follow-ups due", summary.follow_ups_due),
            line("Pending approvals", summary.pending_approvals),
            line("Stale leads", summary.stale_leads),
            line("Errors / needs cleanup", summary.errors),
        ]
    )
