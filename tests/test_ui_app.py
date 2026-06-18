from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from groot_ops import auth
from groot_ops.ui_app import create_app


class InMemoryAuthBackend:
    def __init__(self):
        self.users_by_email = {}
        self.sessions_by_hash = {}
        self.revoked_hashes = set()

    def create_user(self, *, email: str, password: str, full_name: str):
        email_normalized = auth.normalize_email(email)
        if email_normalized in self.users_by_email:
            raise auth.AuthError("An account with this email already exists.")
        user = auth.AuthUser(
            id="00000000-0000-0000-0000-%012d" % (len(self.users_by_email) + 1),
            email=email.strip(),
            full_name=full_name.strip(),
            role="user",
            status="active",
        )
        self.users_by_email[email_normalized] = {
            "user": user,
            "password_hash": auth.hash_password(password),
        }
        return user

    def authenticate_user(self, *, email: str, password: str, user_agent: str = "", ip_address: str = ""):
        record = self.users_by_email.get(auth.normalize_email(email))
        if not record or not auth.verify_password(password, record["password_hash"]):
            raise auth.AuthError("Invalid email or password.")
        token = auth.generate_session_token()
        self.sessions_by_hash[auth.hash_session_token(token)] = record["user"]
        return auth.AuthSession(user=record["user"], token=token, expires_at=datetime.now(timezone.utc))

    def create_session(self, *, user_id: str, user_agent: str = "", ip_address: str = ""):
        for record in self.users_by_email.values():
            if record["user"].id == user_id:
                token = auth.generate_session_token()
                self.sessions_by_hash[auth.hash_session_token(token)] = record["user"]
                return auth.AuthSession(user=record["user"], token=token, expires_at=datetime.now(timezone.utc))
        raise auth.AuthError("User account is not active.")

    def get_user_for_session(self, token: str):
        token_hash = auth.hash_session_token(token)
        if token_hash in self.revoked_hashes:
            return None
        return self.sessions_by_hash.get(token_hash)

    def revoke_session(self, token: str) -> None:
        self.revoked_hashes.add(auth.hash_session_token(token))


def authenticated_client() -> TestClient:
    backend = InMemoryAuthBackend()
    backend.create_user(email="ada@example.com", password="super-secure-passphrase", full_name="Ada Agent")
    client = TestClient(create_app(auth_backend=backend))
    response = client.post(
        "/login",
        data={"email": "ada@example.com", "password": "super-secure-passphrase"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client


@pytest.fixture(autouse=True)
def clear_dashboard_token(monkeypatch):
    monkeypatch.delenv("GROOT_OPS_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("GROOT_OPS_SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("GROOT_OPS_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)


def test_health_route():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_route_reports_db_readiness(monkeypatch):
    class FakeReadiness:
        ok = True
        status = "ok"
        database = "example.com/neondb"
        message = None

        def as_dict(self):
            return {
                "ok": self.ok,
                "status": self.status,
                "database": self.database,
                "message": self.message,
            }

    monkeypatch.setattr("groot_ops.ui_app.check_database_ready", lambda: FakeReadiness())
    client = TestClient(create_app())

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "groot-ops-ui",
        "database": {
            "ok": True,
            "status": "ok",
        },
    }


def test_ready_route_returns_503_when_db_not_ready(monkeypatch):
    class FakeReadiness:
        ok = False
        status = "missing_database_url"
        database = None
        message = "DATABASE_URL is not configured"

        def as_dict(self):
            return {
                "ok": self.ok,
                "status": self.status,
                "database": self.database,
                "message": self.message,
            }

    monkeypatch.setattr("groot_ops.ui_app.check_database_ready", lambda: FakeReadiness())
    client = TestClient(create_app())

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "service": "groot-ops-ui",
        "database": {
            "ok": False,
            "status": "missing_database_url",
        },
    }


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


def test_session_auth_protects_setup_and_client_routes(monkeypatch):
    # Legacy dashboard-token auth must remain ignored after moving to session auth.
    monkeypatch.setenv("GROOT_OPS_DASHBOARD_TOKEN", "pilot-secret")
    client = TestClient(create_app(auth_backend=InMemoryAuthBackend()))

    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    blocked_setup = client.get("/setup", follow_redirects=False)
    assert blocked_setup.status_code == 303
    assert blocked_setup.headers["location"] == "/login?next=%2Fsetup"
    blocked_dashboard = client.get("/clients/example/dashboard", follow_redirects=False)
    assert blocked_dashboard.status_code == 303
    assert blocked_dashboard.headers["location"] == "/login?next=%2Fclients%2Fexample%2Fdashboard"

    token_attempt = client.get("/setup?token=pilot-secret", follow_redirects=False)
    assert token_attempt.status_code == 303
    assert token_attempt.headers["location"].startswith("/login?next=")
    assert "groot_ops_dashboard_token" not in token_attempt.headers.get("set-cookie", "")

    authed = authenticated_client()
    allowed_setup = authed.get("/setup")
    assert allowed_setup.status_code == 200


def test_setup_sends_friendly_email_with_private_dashboard_link(monkeypatch, tmp_path):
    sent = []

    def fake_send_setup_confirmation_email(config, *, dashboard_url):
        sent.append({"config": config, "dashboard_url": dashboard_url})
        return {"channel": "email", "to": config.agent_email, "subject": "sent"}

    monkeypatch.setenv("GROOT_OPS_DASHBOARD_TOKEN", "pilot-secret")
    monkeypatch.setenv("GROOT_OPS_PUBLIC_BASE_URL", "https://groot-ops.vercel.app")
    monkeypatch.setenv("GROOT_OPS_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("GROOT_OPS_DEMO_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("groot_ops.ui_app.send_setup_confirmation_email", fake_send_setup_confirmation_email)
    client = authenticated_client()

    response = client.post(
        "/setup",
        data={
            "business_name": "Sunrise Realty Pilot",
            "agent_name": "Ava Realtor",
            "agent_phone": "+155****0199",
            "agent_email": "ava@example.com",
            "timezone": "America/New_York",
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/sheet123/edit",
            "leads_sheet": "Leads",
            "activity_log_sheet": "Activity Log",
            "owner_channel": "email",
            "owner_destination": "ava@example.com",
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
    assert "Confirmation email sent" in response.text
    assert len(sent) == 1
    assert sent[0]["config"].business_name == "Sunrise Realty Pilot"
    assert sent[0]["dashboard_url"] == "https://groot-ops.vercel.app/clients/sunrise_realty_pilot_ava_realtor/dashboard"


def test_setup_page_uses_client_friendly_controls_and_explanations():
    client = authenticated_client()

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


def test_setup_edit_link_prefills_saved_client_values(monkeypatch, tmp_path):
    monkeypatch.setenv("GROOT_OPS_DEMO_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("MATON_API_KEY", raising=False)
    client = authenticated_client()
    client.post(
        "/setup",
        data={
            "business_name": "Evergreen Realty",
            "agent_name": "Ada Agent",
            "agent_phone": "+155****0100",
            "agent_email": "ada@example.com",
            "timezone": "America/Chicago",
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/sheet123/edit",
            "leads_sheet": "Buyer Leads",
            "activity_log_sheet": "Follow Up Log",
            "column_name": "Client Name",
            "column_phone": "Mobile",
            "column_desired_location": "Preferred Area",
            "column_timeline": "Move Window",
            "column_message": "Inquiry Notes",
            "owner_channel": "email",
            "owner_destination": "ops@example.com",
            "daily_summary_time": "09:15",
            "process_leads_frequency": "manual",
            "hot_timeline_days": "10",
            "warm_timeline_days": "45",
            "stale_after_days": "5",
            "voice": "warm and concise",
            "max_draft_chars": "600",
            "required_disclaimer": "Text STOP to opt out.",
        },
    )

    dashboard = client.get("/clients/evergreen_realty_ada_agent/dashboard")
    assert dashboard.status_code == 200
    assert 'href="/setup?client_id=evergreen_realty_ada_agent"' in dashboard.text

    edit_form = client.get("/setup?client_id=evergreen_realty_ada_agent")

    assert edit_form.status_code == 200
    assert 'name="client_id" value="evergreen_realty_ada_agent"' in edit_form.text
    assert 'value="Evergreen Realty"' in edit_form.text
    assert 'value="Ada Agent"' in edit_form.text
    assert 'value="ada@example.com"' in edit_form.text
    assert 'value="+155****0100"' in edit_form.text
    assert 'value="America/Chicago" selected' in edit_form.text
    assert 'value="sheet123"' in edit_form.text
    assert 'value="Buyer Leads"' in edit_form.text
    assert 'value="Follow Up Log"' in edit_form.text
    assert 'name="column_name" value="Client Name"' in edit_form.text
    assert 'name="column_phone" value="Mobile"' in edit_form.text
    assert 'name="column_desired_location" value="Preferred Area"' in edit_form.text
    assert 'name="column_timeline" value="Move Window"' in edit_form.text
    assert 'name="column_message" value="Inquiry Notes"' in edit_form.text
    assert 'value="email" checked' in edit_form.text
    assert 'value="ops@example.com"' in edit_form.text
    assert 'value="09:15"' in edit_form.text
    assert 'value="manual" selected' in edit_form.text
    assert 'name="hot_timeline_days" value="10"' in edit_form.text
    assert 'name="warm_timeline_days" value="45"' in edit_form.text
    assert 'name="stale_after_days" value="5"' in edit_form.text
    assert 'value="warm and concise"' in edit_form.text
    assert 'name="max_draft_chars" value="600"' in edit_form.text
    assert 'value="Text STOP to opt out."' in edit_form.text


def test_setup_saves_demo_config_and_shows_dashboard_link(monkeypatch, tmp_path):
    monkeypatch.setenv("GROOT_OPS_DEMO_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("MATON_API_KEY", raising=False)
    client = authenticated_client()

    response = client.post(
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
    client = authenticated_client()
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
    assert "Setup saved" in dashboard.text
    assert "Preview mode only" in dashboard.text
    assert "Run safe previews before starting pilot automation" in dashboard.text
    assert "Run safe previews before marking the pilot active" in dashboard.text
    assert "of 4 checks ready" in dashboard.text
    assert "Recent activity" in dashboard.text
    assert "No automation runs yet. Run a preview to see activity here." in dashboard.text
    assert "Save this dashboard link" in dashboard.text
    assert "/clients/confort_properties_alex_john/dashboard" in dashboard.text
    assert "What to do next" in dashboard.text
    assert "1. Run the daily summary preview" in dashboard.text
    assert "2. Preview lead follow-up drafts" in dashboard.text
    assert "3. Mark pilot active" in dashboard.text
    assert "Mark pilot active" in dashboard.text
    assert "Start automation" not in dashboard.text
    assert "ask Groot Ops support/Drax" not in dashboard.text
    assert "Start setup is not the activation button" in dashboard.text
    assert "Edit setup" in dashboard.text
    assert 'class="nav-cta" href="/setup">Start setup' not in dashboard.text
    assert 'class="nav-logout-form" method="post" action="/logout"' in dashboard.text
    assert "Ada Agent" in dashboard.text
    assert "Authentication" not in dashboard.text
    assert "Login" not in dashboard.text


def test_dashboard_marks_mobile_wrapping_targets(monkeypatch, tmp_path):
    monkeypatch.setenv("GROOT_OPS_DEMO_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("MATON_API_KEY", raising=False)
    client = authenticated_client()
    client.post(
        "/setup",
        data={
            "business_name": "Confort Properties With A Very Long Mobile Overflow Name International Realty Group",
            "agent_name": "Alexandria Johnson-Smith The Third",
            "agent_phone": "+155****0100",
            "agent_email": "alexandria@example.com",
            "timezone": "America/New_York",
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/sheet123/edit",
            "leads_sheet": "Leads",
            "activity_log_sheet": "Activity Log",
            "owner_channel": "email",
            "owner_destination": "alexandria@example.com",
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

    dashboard = client.get("/clients/confort_properties_with_a_very_long_mobile_overf/dashboard")

    assert dashboard.status_code == 200
    assert 'class="dashboard-meta" aria-label="Dashboard setup summary"' in dashboard.text
    assert '<span class="meta-label">Agent</span>Alexandria Johnson-Smith The Third' in dashboard.text
    assert '<span class="meta-label">Alerts</span>Email notifications' in dashboard.text
    assert '<span class="meta-label">Cadence</span>Every 2h Weekdays' in dashboard.text
    assert 'class="dashboard-path-code"' in dashboard.text
    assert 'class="schedule-line"' in dashboard.text
    assert 'class="config-path-line"' in dashboard.text


def test_dashboard_shortcut_opens_latest_client_without_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("GROOT_OPS_DEMO_CONFIG_DIR", str(tmp_path))
    client = authenticated_client()
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


def test_dashboard_start_automation_button_sets_active_status(monkeypatch, tmp_path):
    monkeypatch.setenv("GROOT_OPS_DEMO_CONFIG_DIR", str(tmp_path))
    client = authenticated_client()
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
            "process_leads_frequency": "every_2h_weekdays",
            "hot_timeline_days": "14",
            "warm_timeline_days": "60",
            "stale_after_days": "7",
            "voice": "friendly",
            "max_draft_chars": "700",
            "required_disclaimer": "Reply STOP to opt out.",
        },
    )

    response = client.post("/clients/evergreen_realty_ada_agent/activate")

    assert response.status_code == 200
    assert "Automation is on" in response.text
    assert "Pilot automation marked active" in response.text
    assert "Ready to activate" not in response.text
    config_text = (tmp_path / "evergreen_realty_ada_agent.yaml").read_text()
    assert "automation_status: active" in config_text
