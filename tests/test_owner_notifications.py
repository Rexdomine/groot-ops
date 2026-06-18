from __future__ import annotations

import base64
import json
from email import message_from_bytes
from email.policy import default

from groot_ops.config_loader import load_client_config
from groot_ops.daily_summary import DailySummary, format_daily_summary
from groot_ops.models import Lead
from groot_ops.owner_notifications import (
    MatonGmailSender,
    build_owner_setup_confirmation_email,
    build_owner_summary_email,
    send_owner_setup_confirmation_email,
    send_owner_summary_email,
)


def _decode_raw_message(raw: str):
    return message_from_bytes(base64.urlsafe_b64decode(raw.encode("ascii")), policy=default)


def test_build_owner_summary_email_contains_actionable_digest():
    config = load_client_config("configs/sample_realtor.yaml")
    summary = DailySummary(
        new_leads=[Lead(lead_id="L1", name="Ada Buyer")],
        hot_leads=[Lead(lead_id="L1", name="Ada Buyer", lead_temperature="hot")],
        follow_ups_due=[Lead(lead_id="L2", name="Ben Followup")],
        pending_approvals=[Lead(lead_id="L3", name="Cara Approval")],
        stale_leads=[],
        errors=[],
    )

    email = build_owner_summary_email(
        config,
        summary,
        recipient="owner@example.com",
        summary_text=format_daily_summary(summary),
    )

    assert email.to_email == "owner@example.com"
    assert "Groot Ops Daily Summary" in email.subject
    assert "Ada Buyer" in email.text_body
    assert "Ben Followup" in email.html_body
    assert "No customer messages were sent" in email.text_body
    assert "Review pending drafts" in email.text_body


def test_build_owner_setup_confirmation_email_is_branded_and_includes_private_dashboard_link():
    config = load_client_config("configs/sample_realtor.yaml")
    config.business_name = "Sunrise Realty Pilot"
    config.agent_name = "Ava Realtor"
    config.owner_notification_channel = "email"
    config.owner_notification_destination = "ava@example.com"
    config.process_leads_frequency = "every_2h_weekdays"
    config.daily_summary_time = "08:30"

    email = build_owner_setup_confirmation_email(
        config,
        recipient="ava@example.com",
        dashboard_url="https://groot-ops.vercel.app/clients/sunrise/dashboard?token=private-token",
    )

    assert email.to_email == "ava@example.com"
    assert "Groot Ops setup is ready" in email.subject
    assert "Sunrise Realty Pilot" in email.subject
    assert "Your private dashboard" in email.text_body
    assert "https://groot-ops.vercel.app/clients/sunrise/dashboard?token=private-token" in email.text_body
    assert "Copy the link above" not in email.text_body
    assert "Groot Ops command center" in email.html_body
    assert "Your setup is ready" in email.html_body
    assert "Open private dashboard" in email.html_body
    assert "Every 2h Weekdays" in email.html_body
    assert "No customer messages are sent automatically" in email.html_body
    assert "Keep this email" in email.html_body


def test_owner_summary_email_uses_branded_actionable_template(monkeypatch):
    monkeypatch.setenv("GROOT_OPS_PUBLIC_BASE_URL", "https://demo.grootops.ai")
    config = load_client_config("configs/sample_realtor.yaml")
    config.client_id = "sample_realtor"
    summary = DailySummary(
        new_leads=[Lead(lead_id="L1", name="Ada Buyer", email="ada@example.com", phone="+15550101")],
        hot_leads=[Lead(lead_id="L1", name="Ada Buyer", email="ada@example.com", phone="+15550101")],
        follow_ups_due=[Lead(lead_id="L2", name="Ben Followup", phone="+15550202")],
        pending_approvals=[Lead(lead_id="L3", name="Cara Approval", email="cara@example.com")],
        stale_leads=[Lead(lead_id="L4", name="Dan Stale")],
        errors=[Lead(lead_id="L5", name="Error Lead", errors="Missing phone")],
    )

    email = build_owner_summary_email(config, summary, recipient="owner@example.com")

    assert "background:#012d1d" in email.html_body
    assert "Groot Ops command center" in email.html_body
    assert "Open dashboard" in email.html_body
    assert "https://demo.grootops.ai/clients/sample_realtor/dashboard" in email.html_body
    assert "Call now" in email.html_body
    assert "tel:+15550101" in email.html_body
    assert "Email lead" in email.html_body
    assert "mailto:ada@example.com" in email.html_body
    assert "Approve drafts" in email.html_body
    assert "Fix data issues" in email.html_body
    assert "Messages stay in human-review mode" in email.html_body


def test_maton_gmail_sender_sends_base64url_mime(monkeypatch):
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"id": "gmail-message-123"}).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr("groot_ops.owner_notifications.urllib.request.urlopen", fake_urlopen)
    sender = MatonGmailSender(api_key="test-api-key")

    result = sender.send(
        to_email="owner@example.com",
        subject="Groot Ops test",
        text_body="Plain digest",
        html_body="<p>HTML digest</p>",
    )

    assert result["id"] == "gmail-message-123"
    assert len(calls) == 1
    request, timeout = calls[0]
    assert timeout == 30
    assert request.full_url.endswith("/google-mail/gmail/v1/users/me/messages/send")
    assert request.headers["Authorization"] == "Bearer test-api-key"
    payload = json.loads(request.data.decode("utf-8"))
    message = _decode_raw_message(payload["raw"])
    assert message["To"] == "owner@example.com"
    assert message["Subject"] == "Groot Ops test"
    assert "Plain digest" in message.get_body(preferencelist=("plain",)).get_content()
    assert "HTML digest" in message.get_body(preferencelist=("html",)).get_content()


def test_send_owner_summary_email_uses_owner_destination_and_supports_dry_run(monkeypatch):
    config = load_client_config("configs/sample_realtor.yaml")
    config.owner_notification_channel = "email"
    config.owner_notification_destination = "owner@example.com"
    summary = DailySummary([], [], [], [], [], [])

    monkeypatch.delenv("MATON_API_KEY", raising=False)
    result = send_owner_summary_email(config, summary, dry_run=True)

    assert result["dry_run"] is True
    assert result["to"] == "owner@example.com"
    assert result["channel"] == "email"
    assert "Groot Ops Daily Summary" in result["subject"]


def test_send_owner_summary_email_requires_email_channel():
    config = load_client_config("configs/sample_realtor.yaml")
    config.owner_notification_channel = "telegram"
    summary = DailySummary([], [], [], [], [], [])

    try:
        send_owner_summary_email(config, summary, dry_run=True)
    except ValueError as exc:
        assert "owner notification channel must be email" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-email owner channel")


def test_setup_confirmation_dry_runs_reserved_test_recipients():
    config = load_client_config("configs/sample_realtor.yaml")
    config.business_name = "Evergreen Realty"
    config.agent_email = "ada@example.com"
    config.owner_notification_channel = "email"
    config.owner_notification_destination = "alexandria.very.long.email.address@example-real-estate-international.com"

    class SenderThatMustNotRun:
        def send(self, **kwargs):
            raise AssertionError("Reserved test recipients must not be sent through Gmail")

    result = send_owner_setup_confirmation_email(
        config,
        dashboard_url="https://groot-ops.vercel.app/clients/evergreen/dashboard",
        sender=SenderThatMustNotRun(),  # type: ignore[arg-type]
    )

    assert result["dry_run"] is True
    assert result["to"] == "alexandria.very.long.email.address@example-real-estate-international.com"
    assert result["channel"] == "email"
