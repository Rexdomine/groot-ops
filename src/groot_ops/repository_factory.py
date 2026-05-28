from __future__ import annotations

from typing import Protocol

from .activity_log import ActivityLog
from .csv_repository import CsvLeadRepository
from .google_sheets_repository import GoogleSheetsLeadRepository
from .models import ClientConfig, Lead


class LeadRepository(Protocol):
    @property
    def label(self) -> str: ...
    def list_leads(self) -> list[Lead]: ...
    def save_leads(self, leads: list[Lead]) -> None: ...


class ActivityRecorder(Protocol):
    def record(self, event_type: str, lead_id: str, message: str, dry_run: bool = False) -> None: ...


def create_lead_repository(config: ClientConfig):
    if config.repository_type == "csv":
        return CsvLeadRepository(config.leads_csv)
    if config.repository_type == "google_sheets":
        return GoogleSheetsLeadRepository(
            spreadsheet_id=config.spreadsheet_id,
            leads_sheet=config.leads_sheet,
            activity_log_sheet=config.activity_log_sheet,
            credentials_env=config.credentials_env,
            service_account_file=config.service_account_file,
        )
    raise ValueError(f"Unsupported repository.type: {config.repository_type}")


def create_activity_recorder(config: ClientConfig, repository: object | None = None):
    if config.repository_type == "csv":
        return ActivityLog(config.activity_log_csv)
    if config.repository_type == "google_sheets":
        if repository is not None and hasattr(repository, "record_activity"):
            return repository
        return GoogleSheetsLeadRepository(
            spreadsheet_id=config.spreadsheet_id,
            leads_sheet=config.leads_sheet,
            activity_log_sheet=config.activity_log_sheet,
            credentials_env=config.credentials_env,
            service_account_file=config.service_account_file,
        )
    raise ValueError(f"Unsupported repository.type: {config.repository_type}")
