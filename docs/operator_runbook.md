# Operator Runbook

This runbook explains how to operate Groot Ops Phase 1.5 safely for demos and pilots.

## 1. Environment setup

```bash
cd /opt/data/groot-ops
. .venv/bin/activate  # if the venv already exists
python -m pip install -e '.[dev]'
cp .env.example .env  # first-time only; fill local credentials outside git
set -a; . ./.env; set +a
python -m pytest -q
python scripts/production_readiness_check.py
```

## 2. Daily dry-run lead processing

```bash
python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml
```

`--dry-run` is optional because dry-run is the default.

Review each printed lead:

- Score and temperature
- Recommended action
- Draft message
- Approval status
- Errors / missing fields

Dry-run does not write to the CSV, Google Sheet, or activity log.

## 3. Write-mode processing

Only use write mode after reviewing dry-run output:

```bash
python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml --write
```

For pilot-safe testing, restrict processing to one lead or a small batch:

```bash
python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml --lead-id L001
python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml --limit 3
python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml --lead-id L001 --write
python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml --limit 3 --write
```

Write mode updates lead scoring, draft fields, approval queue fields, `updated_at`, `last_run_id`, and the configured activity log.

## 4. Daily summary

```bash
python -m groot_ops.main_daily_summary --client configs/sample_realtor.yaml
```

The summary reports:

- New leads
- Hot leads
- Follow-ups due
- Pending approvals
- Stale leads
- Errors / records needing cleanup

For Phase 2, this output can be delivered by Hermes cron, email, or Telegram after Rex approves the schedule.

## 5. Approval policy

No outbound sending is implemented in Phase 1.5. Operators manually review generated copy and manually send outside Groot Ops. If a future sender is added, it must call `is_send_eligible(lead)` and only proceed when:

- `approval_status` is `approved`
- `draft_message` is present and non-empty
- duplicate-send prevention exists
- the client has explicitly enabled the outbound channel

Approvals are tied to exact draft text. If processing regenerates a different `draft_message`, the row returns to `needs_approval` and approval/send metadata is cleared.

## 6. Error handling

Records with missing phone, budget, location, timeline, or draft validation issues are surfaced in `errors`. Fix the sheet fields, then rerun processing.

Common failures:

- `MATON_API_KEY is not set`: source `.env` or configure the deployment secret.
- `Google Sheets service-account file not found`: fix the env var/path or move credentials outside the repo.
- `Missing repository.spreadsheet_id`: copy from `configs/client.example.yaml` and fill the sheet ID.

## 7. Production readiness check

Run this before every Phase 2 pilot handoff:

```bash
python -m pytest -q
python scripts/production_readiness_check.py
git status --short
```

Only proceed when tests and readiness checks pass and no private config/credential files are staged.
