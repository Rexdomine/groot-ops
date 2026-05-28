# Groot Ops

Groot Ops is an AI operations automation service for small businesses. This repository contains the real-estate Phase 1/1.5 scaffold for lead follow-up and daily business summaries.

Phase 1.5 status: **pilot-ready foundation**. The system can read leads, score them, draft follow-up copy, write internal sheet updates, append activity logs, and print owner summaries. It intentionally does **not** send customer-facing messages.

## What the MVP does

- CSV or Google Sheets lead control center
- Lead scoring into `hot`, `warm`, `cold`, or `needs_info`
- Recommended next action and draft follow-up generation
- Approval queue fields before any send eligibility
- Daily operational summary
- Dry-run mode for safe demos and pilots
- Activity log for write-mode processing
- Maton or native Google Sheets access
- Local tests and GitHub Actions CI
- Production-readiness static check for required docs and obvious secret leaks
- Lightweight FastAPI demo UI for realtor setup, validation, previews, and Vercel deployment

## Quick start

```bash
cd /opt/data/groot-ops
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m pytest -q
python scripts/production_readiness_check.py
```

Run the lead processor in safe dry-run mode:

```bash
python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml
```

Dry-run is the CLI default. To update CSV/log files or Google Sheets, explicitly opt in to write mode:

```bash
python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml --write
```

Run the daily summary:

```bash
python -m groot_ops.main_daily_summary --client configs/sample_realtor.yaml
```

Run the lightweight demo UI locally:

```bash
uv run --extra ui python -m groot_ops.main_ui --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080/setup`.

## Pilot-safe Google Sheets run order

For a new client or new sheet, always run in this order:

```bash
# 1. Read-only summary check
python -m groot_ops.main_daily_summary --client configs/<client>.local.yaml

# 2. Dry-run one row
python -m groot_ops.main_process_leads --client configs/<client>.local.yaml --lead-id L001

# 3. Dry-run small batch
python -m groot_ops.main_process_leads --client configs/<client>.local.yaml --limit 3

# 4. Write one row after review
python -m groot_ops.main_process_leads --client configs/<client>.local.yaml --lead-id L001 --write

# 5. Write small batch after verification
python -m groot_ops.main_process_leads --client configs/<client>.local.yaml --limit 3 --write
```

## Configuration

Safe templates:

- `.env.example`: local environment variable template
- `configs/client.example.yaml`: generic client config template
- `configs/pilot_realtor.example.yaml`: Google Sheets pilot template
- `configs/sample_realtor.yaml`: local CSV demo config

Private files should stay untracked:

- `.env`
- `configs/*.local.yaml`
- `configs/*rex*.yaml`
- service-account JSON files

## Current architecture

- `configs/sample_realtor.yaml`: sample client configuration
- `data/sample_leads.csv`: demo lead sheet compatible with CSV export/import
- `src/groot_ops/config_loader.py`: loads and validates client YAML
- `src/groot_ops/csv_repository.py`: local CSV repository adapter
- `src/groot_ops/google_sheets_repository.py`: Google Sheets adapter with Maton and native service-account support
- `src/groot_ops/repository_factory.py`: repository/activity-log factory for CSV or Google Sheets
- `src/groot_ops/lead_scorer.py`: deterministic scoring rules
- `src/groot_ops/message_drafter.py`: safe template-based draft generator
- `src/groot_ops/approval_queue.py`: approval gate / send eligibility guard
- `src/groot_ops/daily_summary.py`: summary buckets and formatting
- `src/groot_ops/main_process_leads.py`: CLI for scoring and drafting
- `src/groot_ops/main_daily_summary.py`: CLI for summary output
- `src/groot_ops/ui_app.py`: FastAPI demo setup/dashboard app
- `src/groot_ops/main_ui.py`: local UI launcher
- `api/index.py`: Vercel Python serverless entrypoint
- `vercel.json`: Vercel routing/build config
- `scripts/production_readiness_check.py`: CI/local readiness guard

## Documentation

- `docs/sheet_schema.md`: required Sheet/CSV columns
- `docs/google_sheets_setup.md`: Google Sheets setup
- `docs/operator_runbook.md`: day-to-day commands
- `docs/client_onboarding_checklist.md`: pilot onboarding checklist
- `docs/safety_policy.md`: approval, privacy, and no-auto-send rules
- `docs/deployment_cron.md`: Phase 2 scheduling/deployment notes
- `docs/demo_ui_runbook.md`: local/Vercel UI demo instructions and realtor sales script
- `docs/plans/2026-05-28-phase-1-5-production-readiness.md`: implementation plan
- `docs/plans/2026-05-28-lightweight-demo-ui.md`: demo UI implementation plan

## Safety and scope

Phase 1.5 does **not** send SMS, email, WhatsApp, social DMs, or Gmail messages to customers. It only prepares internal draft copy and marks valid drafts as `needs_approval`.

A future sender must only proceed when `approval_status=approved`, `draft_message` is present, the approved text has not changed, duplicate-send prevention exists, and the client has explicitly opted into that channel.

Dry-run mode is the default and prints intended repository updates without writing the lead sheet or activity log. Write mode requires `--write`. Use `--lead-id` or `--limit` to test one/few rows during pilots.

Repository paths in client YAML configs are resolved relative to the config file directory. For example, `configs/sample_realtor.yaml` uses `../data/sample_leads.csv`.

## Google Sheets pilot adapter

Set `repository.type: google_sheets` to use a live Google Sheet with the same schema. Google client imports are lazy/optional, and tests use mocked clients so no live credentials are required in CI.

For Rex/Hermes pilots, the Maton proxy path can use:

```yaml
repository:
  type: google_sheets
  spreadsheet_id: YOUR_SHEET_ID
  credentials_env: MATON_API_KEY
```

Keep credentials out of git; use environment variables and `.env.example` placeholders only.
