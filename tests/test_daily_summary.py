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
