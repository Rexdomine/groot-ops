from datetime import datetime, timezone

from groot_ops.config_loader import load_client_config
from groot_ops.daily_summary import build_daily_summary, format_daily_summary
from groot_ops.main_daily_summary import run_daily_summary
from groot_ops.models import Lead


def test_daily_summary_counts_operational_buckets():
    config = load_client_config("configs/sample_realtor.yaml")
    leads = [
        Lead(
            lead_id="N1",
            name="New Hot",
            status="new",
            lead_temperature="hot",
            approval_status="needs_approval",
            follow_up_due_at="2026-05-27T09:00:00+00:00",
            created_at="2026-05-27T08:00:00+00:00",
        ),
        Lead(
            lead_id="S1",
            name="Stale Error",
            status="contacted",
            errors="missing_phone",
            last_contacted_at="2026-05-01T08:00:00+00:00",
        ),
    ]

    summary = build_daily_summary(leads, config, now=datetime(2026, 5, 28, tzinfo=timezone.utc))
    output = format_daily_summary(summary)

    assert len(summary.new_leads) == 1
    assert len(summary.hot_leads) == 1
    assert len(summary.follow_ups_due) == 1
    assert len(summary.pending_approvals) == 1
    assert len(summary.stale_leads) == 1
    assert len(summary.errors) == 1
    assert "Groot Ops Daily Summary" in output
    assert "Follow-ups due" in output


def test_daily_summary_cli_enriches_unprocessed_sample_sheet():
    output = run_daily_summary("configs/sample_realtor.yaml")

    assert "Hot leads: 1" in output
    assert "Pending approvals: 4" in output
    assert "Errors / needs cleanup: 1" in output


def test_daily_summary_cli_can_email_owner_in_dry_run(monkeypatch):
    monkeypatch.setenv("MATON_API_KEY", "test-key")
    output = run_daily_summary("configs/sample_realtor.yaml", email_owner=True, email_dry_run=True, to_email="owner@example.com")

    assert "Groot Ops Daily Summary" in output
    assert "Owner email dry run prepared for owner@example.com" in output


def test_daily_summary_cli_uses_configured_owner_email_without_override(tmp_path, monkeypatch):
    config_path = tmp_path / "client.yaml"
    config_path.write_text(
        "\n".join(
            [
                "client_id: form_email_client",
                "business_name: Form Email Realty",
                "agent_name: Form Agent",
                "agent_phone: '555-0100'",
                "agent_email: form-email@example.com",
                "repository:",
                "  type: csv",
                "  leads_csv: /opt/data/groot-ops/data/sample_leads.csv",
                "notifications:",
                "  owner_channel: email",
                "  owner_destination: form-email@example.com",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MATON_API_KEY", "test-key")

    output = run_daily_summary(str(config_path), email_owner=True, email_dry_run=True)

    assert "Owner email dry run prepared for form-email@example.com" in output
