from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

from groot_ops.main_process_leads import process_leads


CSV_HEADER = [
    "lead_id",
    "created_at",
    "name",
    "email",
    "phone",
    "source",
    "budget",
    "desired_location",
    "timeline",
    "property_type",
    "message",
    "last_contacted_at",
    "follow_up_due_at",
    "status",
    "approval_status",
    "draft_message",
    "recommended_action",
    "lead_score",
    "lead_temperature",
    "errors",
    "updated_at",
    "approved_by",
    "approved_at",
    "sent_at",
]


def _write_config_and_csv(tmp_path: Path, rows: list[dict[str, str]]) -> tuple[Path, Path, Path]:
    config_dir = tmp_path / "configs"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    leads_csv = data_dir / "leads.csv"
    activity_log_csv = data_dir / "activity_log.csv"

    with leads_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)

    config_path = config_dir / "client.yaml"
    config_path.write_text(
        "\n".join(
            [
                "client_id: test_client",
                "business_name: Test Realty",
                "agent_name: Test Agent",
                "agent_phone: '555-000-0000'",
                "agent_email: agent@example.invalid",
                "repository:",
                "  type: csv",
                "  leads_csv: ../data/leads.csv",
                "  activity_log_csv: ../data/activity_log.csv",
                "messaging:",
                "  required_disclaimer: Reply STOP to opt out.",
            ]
        ),
        encoding="utf-8",
    )
    return config_path, leads_csv, activity_log_csv


def _base_row(**overrides: str) -> dict[str, str]:
    row = {key: "" for key in CSV_HEADER}
    row.update(
        {
            "lead_id": "L100",
            "created_at": "2026-05-27T10:00:00",
            "name": "Jordan Lee",
            "email": "jordan@example.invalid",
            "phone": "555-111-0101",
            "source": "Website",
            "budget": "650000",
            "desired_location": "Downtown",
            "timeline": "7 days",
            "property_type": "Condo",
            "message": "Pre-approved and wants to tour this week.",
            "status": "new",
        }
    )
    row.update(overrides)
    return row


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_process_leads_dry_run_does_not_write_lead_csv_or_activity_log(tmp_path: Path):
    config_path, leads_csv, activity_log_csv = _write_config_and_csv(tmp_path, [_base_row()])
    before = leads_csv.read_text(encoding="utf-8")

    processed = process_leads(str(config_path), dry_run=True)

    assert processed[0].draft_message
    assert leads_csv.read_text(encoding="utf-8") == before
    assert not activity_log_csv.exists()


def test_process_leads_write_mode_writes_expected_fields_and_activity_log(tmp_path: Path):
    config_path, leads_csv, activity_log_csv = _write_config_and_csv(tmp_path, [_base_row()])

    process_leads(str(config_path), dry_run=False)

    row = _read_rows(leads_csv)[0]
    assert row["lead_score"] == "100"
    assert row["lead_temperature"] == "hot"
    assert row["recommended_action"] == "Call or text now and offer specific showing times."
    assert row["approval_status"] == "needs_approval"
    assert "Reply STOP to opt out." in row["draft_message"]
    assert row["updated_at"]
    assert activity_log_csv.exists()
    assert "lead_processed" in activity_log_csv.read_text(encoding="utf-8")


def test_approved_draft_regeneration_resets_approval_and_clears_metadata(tmp_path: Path):
    config_path, leads_csv, _activity_log_csv = _write_config_and_csv(
        tmp_path,
        [
            _base_row(
                approval_status="approved",
                draft_message="Previously approved stale copy.",
                approved_by="manager@example.invalid",
                approved_at="2026-05-27T12:00:00+00:00",
                sent_at="2026-05-27T12:05:00+00:00",
            )
        ],
    )

    process_leads(str(config_path), dry_run=False)

    row = _read_rows(leads_csv)[0]
    assert row["draft_message"] != "Previously approved stale copy."
    assert row["approval_status"] == "needs_approval"
    assert row["approved_by"] == ""
    assert row["approved_at"] == ""
    assert row["sent_at"] == ""


def test_cli_defaults_to_dry_run_and_requires_write_for_file_updates(tmp_path: Path):
    config_path, leads_csv, activity_log_csv = _write_config_and_csv(tmp_path, [_base_row()])
    before = leads_csv.read_text(encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[1]
    subprocess_env = {**os.environ, "PYTHONPATH": str(repo_root / "src")}

    result = subprocess.run(
        [sys.executable, "-m", "groot_ops.main_process_leads", "--client", str(config_path)],
        cwd=repo_root,
        env=subprocess_env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Mode: DRY RUN (no writes)" in result.stdout
    assert leads_csv.read_text(encoding="utf-8") == before
    assert not activity_log_csv.exists()

    write_result = subprocess.run(
        [sys.executable, "-m", "groot_ops.main_process_leads", "--client", str(config_path), "--write"],
        cwd=repo_root,
        env=subprocess_env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert write_result.returncode == 0, write_result.stderr
    assert "Mode: WRITE" in write_result.stdout
    assert _read_rows(leads_csv)[0]["approval_status"] == "needs_approval"
    assert activity_log_csv.exists()
