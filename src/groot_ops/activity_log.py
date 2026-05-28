from __future__ import annotations

import csv
from pathlib import Path

from .models import utc_now_iso


class ActivityLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def record(self, event_type: str, lead_id: str, message: str, dry_run: bool = False) -> None:
        if dry_run:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists()
        with self.path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "event_type", "lead_id", "message"])
            if not exists:
                writer.writeheader()
            writer.writerow(
                {"timestamp": utc_now_iso(), "event_type": event_type, "lead_id": lead_id, "message": message}
            )
