from __future__ import annotations

import csv
from pathlib import Path

from .models import Lead


DEFAULT_FIELDS = [
    "lead_id",
    "created_at",
    "name",
    "email",
    "phone",
    "source",
    "budget",
    "desired_location",
    "timeline",
    "property_type",
    "message",
    "last_contacted_at",
    "follow_up_due_at",
    "status",
    "approval_status",
    "draft_message",
    "recommended_action",
    "lead_score",
    "lead_temperature",
    "errors",
    "updated_at",
    "approved_by",
    "approved_at",
    "sent_at",
    "approval_notes",
    "sent_by",
    "last_run_id",
]


class CsvLeadRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @property
    def label(self) -> str:
        return str(self.path)

    def list_leads(self) -> list[Lead]:
        if not self.path.exists():
            raise FileNotFoundError(f"Lead CSV not found: {self.path}")
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            return [Lead.from_dict(row) for row in csv.DictReader(handle)]

    def save_leads(self, leads: list[Lead]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(DEFAULT_FIELDS)
        for lead in leads:
            for key in lead.extra:
                if key not in fieldnames:
                    fieldnames.append(key)
        with self.path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for lead in leads:
                writer.writerow(lead.to_dict())
