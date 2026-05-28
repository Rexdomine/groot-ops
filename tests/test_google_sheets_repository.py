from __future__ import annotations

from groot_ops.config_loader import load_client_config
from groot_ops.google_sheets_repository import GoogleSheetsLeadRepository
from groot_ops.main_process_leads import process_leads
from groot_ops.repository_factory import create_lead_repository


class _Call:
    def __init__(self, response=None, on_execute=None):
        self.response = response or {}
        self.on_execute = on_execute

    def execute(self):
        if self.on_execute:
            self.on_execute()
        return self.response


class FakeValues:
    def __init__(self):
        self.updated = []
        self.appended = []
        self.get_calls = []
        self.values = [
            ["lead_id", "name", "phone", "timeline", "approval_status", "draft_message"],
            ["L1", "Jordan Lee", "555-0101", "7 days", "", ""],
        ]

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return _Call({"values": self.values})

    def update(self, **kwargs):
        self.updated.append(kwargs)
        return _Call({"updatedRows": len(kwargs["body"]["values"])})

    def append(self, **kwargs):
        self.appended.append(kwargs)
        return _Call({"updates": {"updatedRows": 1}})


class FakeSheets:
    def __init__(self, values):
        self._values = values

    def values(self):
        return self._values


class FakeClient:
    def __init__(self, values):
        self._values = values

    def spreadsheets(self):
        return FakeSheets(self._values)


def test_google_sheets_repository_read_write_and_activity_dry_run():
    values = FakeValues()
    repo = GoogleSheetsLeadRepository(
        spreadsheet_id="sheet123",
        leads_sheet="Leads",
        activity_log_sheet="Activity Log",
        client=FakeClient(values),
    )

    leads = repo.list_leads()
    assert leads[0].lead_id == "L1"
    assert leads[0].name == "Jordan Lee"

    leads[0].lead_score = "100"
    leads[0].extra["approval_notes"] = "manager review"
    repo.save_leads(leads)
    assert values.updated[0]["spreadsheetId"] == "sheet123"
    assert values.updated[0]["range"] == "Leads!A1"
    assert "approval_notes" in values.updated[0]["body"]["values"][0]

    repo.record_activity("lead_processed", "L1", "hot:needs_approval", dry_run=True)
    assert values.appended == []
    repo.record("lead_processed", "L1", "hot:needs_approval", dry_run=False)
    assert values.appended[0]["range"] == "Activity Log!A1"


def test_repository_factory_selects_google_sheets(tmp_path):
    config_path = tmp_path / "client.yaml"
    config_path.write_text(
        "\n".join(
            [
                "client_id: pilot_client",
                "business_name: Pilot Realty",
                "agent_name: Agent",
                "agent_phone: '555-0100'",
                "agent_email: agent@example.invalid",
                "repository:",
                "  type: google_sheets",
                "  spreadsheet_id: sheet123",
                "  credentials_env: GROOT_GOOGLE_SERVICE_ACCOUNT_JSON",
            ]
        ),
        encoding="utf-8",
    )

    repo = create_lead_repository(load_client_config(config_path))

    assert isinstance(repo, GoogleSheetsLeadRepository)
    assert repo.spreadsheet_id == "sheet123"


def test_process_leads_with_google_sheets_repository_records_activity(tmp_path, monkeypatch):
    values = FakeValues()
    repo = GoogleSheetsLeadRepository(
        spreadsheet_id="sheet123",
        leads_sheet="Leads",
        activity_log_sheet="Activity Log",
        client=FakeClient(values),
    )
    config_path = tmp_path / "client.yaml"
    config_path.write_text(
        "\n".join(
            [
                "client_id: pilot_client",
                "business_name: Pilot Realty",
                "agent_name: Agent",
                "agent_phone: '555-0100'",
                "agent_email: agent@example.invalid",
                "repository:",
                "  type: google_sheets",
                "  spreadsheet_id: sheet123",
                "  credentials_env: GROOT_GOOGLE_SERVICE_ACCOUNT_JSON",
            ]
        ),
        encoding="utf-8",
    )
    import groot_ops.main_process_leads as processor

    monkeypatch.setattr(processor, "create_lead_repository", lambda _config: repo)
    monkeypatch.setattr(processor, "create_activity_recorder", lambda _config, repository=None: repository)

    processed = process_leads(str(config_path), dry_run=False)

    assert processed[0].lead_id == "L1"
    assert values.updated, "write mode should save processed leads back to Google Sheets"
    assert values.appended, "write mode should append an activity log row"
    assert values.appended[0]["body"]["values"][0][1] == "lead_processed"
