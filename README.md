# Groot Ops

Groot Ops is an AI operations automation service. This repository contains the Phase 1 MVP scaffold for real estate lead follow-up and daily business summaries.

The MVP is intentionally lightweight:

- CSV / Google-Sheets-compatible lead control center
- Lead scoring into `hot`, `warm`, `cold`, or `needs_info`
- Recommended next action and draft follow-up generation
- Approval queue fields before any send eligibility
- Daily operational summary
- Dry-run mode for safe demos
- Activity log for write-mode processing
- Local tests with no Google credentials or outbound sending

## Quick start

```bash
cd /opt/data/groot-ops
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src pytest
```

Run the lead processor in safe dry-run mode:

```bash
PYTHONPATH=src python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml
```

Dry-run is the CLI default. To update CSV/log files, explicitly opt in to write mode:

```bash
PYTHONPATH=src python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml --write
```

Run the daily summary:

```bash
PYTHONPATH=src python -m groot_ops.main_daily_summary --client configs/sample_realtor.yaml
```

If installed as a package (`pip install -e .`), `PYTHONPATH=src` is not required.

## Current architecture

- `configs/sample_realtor.yaml`: sample client configuration
- `data/sample_leads.csv`: demo lead sheet compatible with CSV export/import
- `src/groot_ops/config_loader.py`: loads and validates client YAML
- `src/groot_ops/csv_repository.py`: local CSV repository adapter
- `src/groot_ops/google_sheets_repository.py`: Google Sheets repository adapter with lazy optional Google imports
- `src/groot_ops/repository_factory.py`: repository/activity-log factory for CSV or Google Sheets
- `src/groot_ops/lead_scorer.py`: deterministic scoring rules
- `src/groot_ops/message_drafter.py`: safe template-based draft generator
- `src/groot_ops/approval_queue.py`: approval gate / send eligibility guard
- `src/groot_ops/daily_summary.py`: summary buckets and formatting
- `src/groot_ops/main_process_leads.py`: CLI for scoring and drafting
- `src/groot_ops/main_daily_summary.py`: CLI for summary output

## Safety and scope

Phase 1 does **not** send SMS, email, or social messages. It only prepares internal draft copy and marks valid drafts as `needs_approval`. A lead is send-eligible only when `approval_status=approved` and `draft_message` is present. If automation regenerates draft copy that differs from the previously approved copy, approval is reset to `needs_approval` and approval/send metadata is cleared.

Dry-run mode is the default and prints intended repository updates without writing the lead sheet or activity log. Write mode requires `--write`. Use `--lead-id` or `--limit` to test one/few rows during pilots.

Repository paths in client YAML configs are resolved relative to the config file directory. For example, `configs/sample_realtor.yaml` uses `../data/sample_leads.csv`.

## Google Sheets pilot adapter

Set `repository.type: google_sheets` to use a live Google Sheet with the same schema. See `configs/pilot_realtor.example.yaml` and `docs/google_sheets_setup.md`. Google client imports are lazy/optional, and tests use mocked clients so no live credentials are required in CI.

Keep credentials out of git; use environment variables and `.env.example` placeholders only.
