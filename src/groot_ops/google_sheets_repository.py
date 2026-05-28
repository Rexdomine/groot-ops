from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Protocol

from .csv_repository import DEFAULT_FIELDS
from .models import Lead, utc_now_iso
from .sheet_mapping import infer_column_mapping, map_sheet_row, row_for_original_headers


class GoogleSheetsConfigurationError(RuntimeError):
    """Raised when Google Sheets dependencies or credentials are not configured."""


class GoogleSheetsValuesClient(Protocol):
    def get(self, **kwargs: Any) -> Any: ...
    def update(self, **kwargs: Any) -> Any: ...
    def append(self, **kwargs: Any) -> Any: ...


class _MatonExecute:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def execute(self) -> dict[str, Any]:
        return self.payload


class MatonGoogleSheetsValuesClient:
    """Small Google Sheets values client backed by Maton's Google Sheets proxy."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://api.maton.ai/google-sheets/v4/spreadsheets"

    def _request(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}

    def _range_url(self, spreadsheet_id: str, range_name: str, suffix: str = "") -> str:
        encoded_range = urllib.parse.quote(range_name, safe="")
        return f"{self.base_url}/{spreadsheet_id}/values/{encoded_range}{suffix}"

    def get(self, **kwargs: Any) -> _MatonExecute:
        spreadsheet_id = kwargs["spreadsheetId"]
        range_name = kwargs["range"]
        payload = self._request("GET", self._range_url(spreadsheet_id, range_name))
        return _MatonExecute(payload)

    def update(self, **kwargs: Any) -> _MatonExecute:
        spreadsheet_id = kwargs["spreadsheetId"]
        range_name = kwargs["range"]
        value_input_option = kwargs.get("valueInputOption", "RAW")
        body = kwargs.get("body") or {}
        suffix = f"?valueInputOption={urllib.parse.quote(str(value_input_option), safe='')}"
        payload = self._request("PUT", self._range_url(spreadsheet_id, range_name, suffix), body)
        return _MatonExecute(payload)

    def append(self, **kwargs: Any) -> _MatonExecute:
        spreadsheet_id = kwargs["spreadsheetId"]
        range_name = kwargs["range"]
        value_input_option = kwargs.get("valueInputOption", "RAW")
        insert_data_option = kwargs.get("insertDataOption", "INSERT_ROWS")
        body = kwargs.get("body") or {}
        query = urllib.parse.urlencode(
            {"valueInputOption": value_input_option, "insertDataOption": insert_data_option}
        )
        payload = self._request("POST", self._range_url(spreadsheet_id, range_name, f":append?{query}"), body)
        return _MatonExecute(payload)


class MatonGoogleSheetsService:
    def __init__(self, api_key: str) -> None:
        self._values = MatonGoogleSheetsValuesClient(api_key)

    def spreadsheets(self) -> "MatonGoogleSheetsService":
        return self

    def values(self) -> MatonGoogleSheetsValuesClient:
        return self._values


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
        column_mapping: dict[str, str] | None = None,
        client: Any | None = None,
    ) -> None:
        if not spreadsheet_id:
            raise ValueError("Missing repository.spreadsheet_id for google_sheets repository")
        self.spreadsheet_id = spreadsheet_id
        self.leads_sheet = leads_sheet or "Leads"
        self.activity_log_sheet = activity_log_sheet or "Activity Log"
        self.credentials_env = credentials_env
        self.service_account_file = service_account_file
        self.column_mapping = column_mapping or {}
        self._last_headers: list[str] = []
        self._last_mapping: dict[str, str] = {}
        self._client = client

    @property
    def label(self) -> str:
        return f"Google Sheets spreadsheet {self.spreadsheet_id} / sheet {self.leads_sheet}"

    def _values(self) -> GoogleSheetsValuesClient:
        client = self._client or self._build_client()
        return client.spreadsheets().values()

    def _build_client(self) -> Any:
        if self.credentials_env == "MATON_API_KEY":
            api_key = os.environ.get("MATON_API_KEY", "")
            if not api_key:
                raise GoogleSheetsConfigurationError("MATON_API_KEY is not set for Maton Google Sheets access.")
            self._client = MatonGoogleSheetsService(api_key)
            return self._client

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
        mapping = infer_column_mapping(headers, self.column_mapping)
        self._last_headers = headers
        self._last_mapping = mapping
        leads: list[Lead] = []
        for row in values[1:]:
            data = map_sheet_row(headers, row, mapping)
            if any(str(value).strip() for value in data.values()):
                leads.append(Lead.from_dict(data))
        return leads

    def save_leads(self, leads: list[Lead]) -> None:
        original_headers = [header for header in self._last_headers if header]
        mapping = self._last_mapping or infer_column_mapping(original_headers, self.column_mapping)
        fieldnames = list(original_headers) if original_headers else list(DEFAULT_FIELDS)
        for lead in leads:
            for key, value in lead.to_dict().items():
                if key.startswith("original_"):
                    continue
                mapped_header = mapping.get(key)
                if mapped_header and mapped_header not in fieldnames:
                    fieldnames.append(mapped_header)
                elif not mapped_header and key not in fieldnames:
                    fieldnames.append(key)
        rows = [fieldnames]
        for lead in leads:
            data = lead.to_dict()
            rows.append(row_for_original_headers(data, fieldnames, mapping))
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
