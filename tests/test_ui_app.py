from fastapi.testclient import TestClient

from groot_ops.ui_app import create_app


def test_health_route():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_setup_page_uses_client_friendly_controls_and_explanations():
    client = TestClient(create_app())

    response = client.get("/setup")

    assert response.status_code == 200
    assert '<select name="timezone"' in response.text
    assert '<input type="time" name="daily_summary_time"' in response.text
    assert 'Hot leads: people likely to move soon' in response.text
    assert 'Warm leads: interested, but not urgent yet' in response.text
    assert 'Stale leads: no recent response' in response.text
    assert 'What these fields mean' in response.text
    assert 'Recommended default' in response.text


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
