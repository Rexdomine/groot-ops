from fastapi.testclient import TestClient

from groot_ops.ui_app import create_app


def test_health_route():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_homepage_uses_stitch_inspired_production_sections():
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Turn real estate leads into daily follow-up action." in response.text
    assert "Daily Pulse" in response.text
    assert "Human approval stays in control." in response.text
    assert "Ready to stop losing leads?" in response.text
    assert "What Groot handles" in response.text
    assert "this demo" not in response.text.lower()
    assert "for demos" not in response.text.lower()


def test_setup_page_uses_client_friendly_controls_and_explanations():
    client = TestClient(create_app())

    response = client.get("/setup")

    assert response.status_code == 200
    assert '<select name="timezone"' in response.text
    assert '<input type="time" name="daily_summary_time"' in response.text
    assert 'Setup Health' in response.text
    assert 'Step 1 of 5: Profile' in response.text
    assert 'Guided setup, not a technical form.' in response.text
    assert 'What these fields mean' in response.text
    assert 'Recommended default' in response.text
    assert 'When should a lead become urgent?' in response.text
    assert 'If the lead says they want to buy, sell, or tour within this many days' in response.text
    assert 'When should Groot keep nurturing instead of marking the lead urgent?' in response.text
    assert 'When should Groot remind the agent to re-engage?' in response.text
    assert 'Urgent lead window' in response.text
    assert 'Nurture window' in response.text
    assert 'Re-engage reminder' in response.text
    assert 'Message Settings' in response.text
    assert 'value="email"' in response.text
    assert 'value="email" disabled' not in response.text
    assert 'value="whatsapp" disabled' in response.text
    assert 'WhatsApp is not available yet' in response.text
    assert 'onclick="this.querySelector(\'input\').checked = true"' in response.text
    assert 'data-step-target="notifications"' in response.text
    assert 'data-setup-step="notifications"' in response.text
    assert 'function updateSetupProgress' in response.text
    assert "setupForm.addEventListener('focusin'" in response.text
    assert 'Google Sheet URL or ID' in response.text
    assert 'Smart column matching' in response.text
    assert 'Groot can work with your existing sheet columns' in response.text
    assert 'name="column_name"' in response.text
    assert 'name="column_phone"' in response.text
    assert 'name="column_desired_location"' in response.text
    assert 'name="column_timeline"' in response.text
    assert 'name="column_message"' in response.text
    assert 'this demo' not in response.text.lower()
    assert 'for demos' not in response.text.lower()
    assert 'manual demo' not in response.text.lower()


def test_setup_saves_demo_config_and_shows_dashboard_link(monkeypatch, tmp_path):
    monkeypatch.setenv("GROOT_OPS_DEMO_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("MATON_API_KEY", raising=False)
    client = TestClient(create_app())

    response = client.post(
        "/setup",
        data={
            "business_name": "Evergreen Realty",
            "agent_name": "Ada Agent",
            "agent_phone": "+15550100",
            "agent_email": "ada@example.com",
            "timezone": "America/New_York",
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/sheet123/edit",
            "leads_sheet": "Leads",
            "activity_log_sheet": "Activity Log",
            "owner_channel": "telegram",
            "owner_destination": "@ada",
            "daily_summary_time": "08:30",
            "process_leads_frequency": "every_2h_weekdays",
            "hot_timeline_days": "14",
            "warm_timeline_days": "60",
            "stale_after_days": "7",
            "voice": "friendly",
            "max_draft_chars": "700",
            "required_disclaimer": "Reply STOP to opt out.",
        },
    )

    assert response.status_code == 200
    assert "Setup saved" in response.text
    assert (tmp_path / "evergreen_realty_ada_agent.yaml").exists()

    dashboard = client.get("/clients/evergreen_realty_ada_agent/dashboard")
    assert dashboard.status_code == 200
    assert "Evergreen Realty" in dashboard.text
    assert "No automatic customer messages" in dashboard.text or "does not send" in dashboard.text


def test_dashboard_uses_stitch_inspired_supported_sections(monkeypatch, tmp_path):
    monkeypatch.setenv("GROOT_OPS_DEMO_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("MATON_API_KEY", raising=False)
    client = TestClient(create_app())
    client.post(
        "/setup",
        data={
            "business_name": "Confort Properties",
            "agent_name": "Alex John",
            "agent_phone": "+155****0100",
            "agent_email": "alex@example.com",
            "timezone": "America/New_York",
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/sheet123/edit",
            "leads_sheet": "Leads",
            "activity_log_sheet": "Activity Log",
            "owner_channel": "email",
            "owner_destination": "alex@example.com",
            "daily_summary_time": "08:30",
            "process_leads_frequency": "manual",
            "hot_timeline_days": "14",
            "warm_timeline_days": "60",
            "stale_after_days": "7",
            "voice": "friendly",
            "max_draft_chars": "700",
            "required_disclaimer": "Reply STOP to opt out.",
        },
    )

    dashboard = client.get("/clients/confort_properties_alex_john/dashboard")

    assert dashboard.status_code == 200
    assert "Setup active" in dashboard.text
    assert "Preview mode only" in dashboard.text
    assert "Run safe previews before enabling live scheduling" in dashboard.text
    assert "of 4 checks ready" in dashboard.text
    assert "Recent activity" in dashboard.text
    assert "No automation runs yet. Run a preview to see activity here." in dashboard.text
    assert "Save this dashboard link" in dashboard.text
    assert "/clients/confort_properties_alex_john/dashboard" in dashboard.text
    assert "Authentication" not in dashboard.text
    assert "Login" not in dashboard.text


def test_dashboard_shortcut_opens_latest_client_without_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("GROOT_OPS_DEMO_CONFIG_DIR", str(tmp_path))
    client = TestClient(create_app())
    client.post(
        "/setup",
        data={
            "business_name": "Evergreen Realty",
            "agent_name": "Ada Agent",
            "agent_phone": "+155****0100",
            "agent_email": "ada@example.com",
            "timezone": "America/New_York",
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/sheet123/edit",
            "leads_sheet": "Leads",
            "activity_log_sheet": "Activity Log",
            "owner_channel": "email",
            "owner_destination": "ada@example.com",
            "daily_summary_time": "08:30",
            "process_leads_frequency": "manual",
            "hot_timeline_days": "14",
            "warm_timeline_days": "60",
            "stale_after_days": "7",
            "voice": "friendly",
            "max_draft_chars": "700",
            "required_disclaimer": "Reply STOP to opt out.",
        },
    )

    response = client.get("/dashboard", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/clients/evergreen_realty_ada_agent/dashboard"
