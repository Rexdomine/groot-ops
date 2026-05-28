from __future__ import annotations

import json
import os
from typing import Any, Protocol

from .csv_repository import DEFAULT_FIELDS
from .models import Lead, utc_now_iso


class GoogleSheetsConfigurationError(RuntimeError):
    """Raised when Google Sheets dependencies or credentials are not configured."""


class GoogleSheetsValuesClient(Protocol):
    def get(self, **kwargs: Any) -> Any: ...
    def update(self, **kwargs: Any) -> Any: ...
    def append(self, **kwargs: Any) -> Any: ...


class GoogleSheetsLeadRepository:
    """Google Sheets-backed Lead repository.

    The optional ``client`` argument is intentionally dependency-injected for tests.
    In production, omit it and the repository lazily builds a Google API Sheets v4
    service from service-account credentials.
    """

    def __init__(
        self,
        *,
        spreadsheet_id: str,
        leads_sheet: str = "Leads",
        activity_log_sheet: str = "Activity Log",
        credentials_env: str | None = None,
        service_account_file: str | None = None,
        client: Any | None = None,
    ) -> None:
        if not spreadsheet_id:
            raise ValueError("Missing repository.spreadsheet_id for google_sheets repository")
        self.spreadsheet_id = spreadsheet_id
        self.leads_sheet = leads_sheet or "Leads"
        self.activity_log_sheet = activity_log_sheet or "Activity Log"
        self.credentials_env = credentials_env
        self.service_account_file = service_account_file
        self._client = client

    @property
    def label(self) -> str:
        return f"Google Sheets spreadsheet {self.spreadsheet_id} / sheet {self.leads_sheet}"

    def _values(self) -> GoogleSheetsValuesClient:
        client = self._client or self._build_client()
        return client.spreadsheets().values()

    def _build_client(self) -> Any:
        try:
            from google.oauth2 import service_account  # type: ignore
            from googleapiclient.discovery import build  # type: ignore
        except ImportError as exc:
            raise GoogleSheetsConfigurationError(
                "Google Sheets repository requires optional Google packages. "
                "Install google-api-python-client and google-auth, or inject a mocked client in tests."
            ) from exc

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        credentials_value = os.environ.get(self.credentials_env, "") if self.credentials_env else ""
        configured_file = os.path.expandvars(os.path.expanduser(self.service_account_file or ""))

        if credentials_value.strip().startswith("{"):
            try:
                credentials_info = json.loads(credentials_value)
                credentials = service_account.Credentials.from_service_account_info(
                    credentials_info, scopes=scopes
                )
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                raise GoogleSheetsConfigurationError(
                    f"Google Sheets credentials env var {self.credentials_env} does not contain valid service-account JSON."
                ) from exc
        else:
            credential_file = credentials_value or configured_file
            if not credential_file:
                raise GoogleSheetsConfigurationError(
                    "Google Sheets credentials are not configured. Set repository.credentials_env "
                    "to an env var containing service-account JSON or a credential file path, "
                    "or set repository.service_account_file to a path/env-expanded path."
                )
            credential_file = os.path.expandvars(os.path.expanduser(credential_file))
            if not os.path.exists(credential_file):
                raise GoogleSheetsConfigurationError(f"Google Sheets service-account file not found: {credential_file}")
            credentials = service_account.Credentials.from_service_account_file(credential_file, scopes=scopes)

        self._client = build("sheets", "v4", credentials=credentials)
        return self._client

    def list_leads(self) -> list[Lead]:
        result = self._values().get(spreadsheetId=self.spreadsheet_id, range=self.leads_sheet).execute()
        values = result.get("values", [])
        if not values:
            return []
        headers = [str(header).strip() for header in values[0]]
        leads: list[Lead] = []
        for row in values[1:]:
            data = {header: (row[index] if index < len(row) else "") for index, header in enumerate(headers) if header}
            if any(str(value).strip() for value in data.values()):
                leads.append(Lead.from_dict(data))
        return leads

    def save_leads(self, leads: list[Lead]) -> None:
        fieldnames = list(DEFAULT_FIELDS)
        for lead in leads:
            for key in lead.extra:
                if key not in fieldnames:
                    fieldnames.append(key)
        rows = [fieldnames]
        for lead in leads:
            data = lead.to_dict()
            rows.append([data.get(field, "") for field in fieldnames])
        self._values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.leads_sheet}!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()

    def record(self, event_type: str, lead_id: str, message: str, dry_run: bool = False) -> None:
        """Record an activity event using the common ActivityRecorder interface."""
        self.record_activity(event_type, lead_id, message, dry_run=dry_run)

    def record_activity(self, event_type: str, lead_id: str, message: str, dry_run: bool = False) -> None:
        if dry_run:
            return
        self._values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{self.activity_log_sheet}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[utc_now_iso(), event_type, lead_id, message]]},
        ).execute()
