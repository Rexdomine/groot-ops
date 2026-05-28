from __future__ import annotations

from groot_ops.config_loader import load_client_config
from groot_ops.google_sheets_repository import GoogleSheetsLeadRepository, MatonGoogleSheetsValuesClient
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


def test_maton_values_client_uses_google_sheets_proxy_endpoints(monkeypatch):
    client = MatonGoogleSheetsValuesClient("test-api-key")
    calls = []

    def fake_request(method, url, body=None):
        calls.append((method, url, body))
        return {"values": [["lead_id"], ["L1"]]}

    monkeypatch.setattr(client, "_request", fake_request)

    assert client.get(spreadsheetId="sheet123", range="Leads!A1:B2").execute()["values"][1][0] == "L1"
    client.update(
        spreadsheetId="sheet123",
        range="Leads!A1",
        valueInputOption="RAW",
        body={"values": [["lead_id"], ["L1"]]},
    ).execute()
    client.append(
        spreadsheetId="sheet123",
        range="Activity Log!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [["now", "lead_processed", "L1", "hot"]]},
    ).execute()

    assert calls[0][0] == "GET"
    assert calls[0][1] == "https://api.maton.ai/google-sheets/v4/spreadsheets/sheet123/values/Leads%21A1%3AB2"
    assert calls[1][0] == "PUT"
    assert calls[1][1].endswith("/values/Leads%21A1?valueInputOption=RAW")
    assert calls[2][0] == "POST"
    assert "/values/Activity%20Log%21A1:append?" in calls[2][1]

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


def test_google_sheets_repository_maps_realtor_headers_without_sheet_reformatting():
    values = FakeValues()
    values.values = [
        ["Client Name", "WhatsApp Number", "Email Address", "Price Range", "Preferred Area", "Move-in Timeline", "Inquiry Notes"],
        ["Amara Okafor", "+2348012345678", "amara@example.com", "$300k-$450k", "Lekki Phase 1", "30 days", "Needs a 3-bedroom apartment"],
    ]
    repo = GoogleSheetsLeadRepository(
        spreadsheet_id="sheet123",
        leads_sheet="Leads",
        activity_log_sheet="Activity Log",
        client=FakeClient(values),
    )

    leads = repo.list_leads()

    assert leads[0].lead_id == "amara_okafor"
    assert leads[0].name == "Amara Okafor"
    assert leads[0].phone == "+2348012345678"
    assert leads[0].email == "amara@example.com"
    assert leads[0].budget == "$300k-$450k"
    assert leads[0].desired_location == "Lekki Phase 1"
    assert leads[0].timeline == "30 days"
    assert leads[0].message == "Needs a 3-bedroom apartment"
    assert leads[0].extra["original_Client Name"] == "Amara Okafor"


def test_google_sheets_repository_honors_saved_column_mapping():
    values = FakeValues()
    values.values = [
        ["Customer", "Mobile", "Custom Lead ID", "Notes"],
        ["Jordan Lee", "555-0101", "CRM-77", "Wants a duplex"],
    ]
    repo = GoogleSheetsLeadRepository(
        spreadsheet_id="sheet123",
        leads_sheet="Leads",
        activity_log_sheet="Activity Log",
        column_mapping={"name": "Customer", "phone": "Mobile", "lead_id": "Custom Lead ID", "message": "Notes"},
        client=FakeClient(values),
    )

    lead = repo.list_leads()[0]

    assert lead.lead_id == "CRM-77"
    assert lead.name == "Jordan Lee"
    assert lead.phone == "555-0101"
    assert lead.message == "Wants a duplex"


def test_google_sheets_repository_preserves_original_headers_when_saving_mapped_leads():
    values = FakeValues()
    values.values = [
        ["Client Name", "WhatsApp Number", "Move-in Timeline"],
        ["Amara Okafor", "+2348012345678", "30 days"],
    ]
    repo = GoogleSheetsLeadRepository(
        spreadsheet_id="sheet123",
        leads_sheet="Leads",
        activity_log_sheet="Activity Log",
        client=FakeClient(values),
    )
    leads = repo.list_leads()
    leads[0].lead_temperature = "hot"

    repo.save_leads(leads)

    saved_headers = values.updated[0]["body"]["values"][0]
    saved_row = values.updated[0]["body"]["values"][1]
    assert saved_headers[:3] == ["Client Name", "WhatsApp Number", "Move-in Timeline"]
    assert saved_row[:3] == ["Amara Okafor", "+2348012345678", "30 days"]
    assert "lead_temperature" in saved_headers


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
