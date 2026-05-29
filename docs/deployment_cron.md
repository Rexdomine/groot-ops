# Deployment and Cron Runbook

This guide prepares Groot Ops for a Phase 2 pilot deployment without enabling automation prematurely.

## Local production-style setup

```bash
cd /opt/data/groot-ops
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
# Fill .env with local-only credentials, then source it for manual runs.
set -a; . ./.env; set +a
python -m pytest -q
python scripts/production_readiness_check.py
```

## First client smoke test

Always run in this order:

```bash
# 1. Read-only summary check
python -m groot_ops.main_daily_summary --client configs/<client>.local.yaml

# 2. Dry-run one row
python -m groot_ops.main_process_leads --client configs/<client>.local.yaml --lead-id L001

# 3. Dry-run small batch
python -m groot_ops.main_process_leads --client configs/<client>.local.yaml --limit 3

# 4. Write one row only after review
python -m groot_ops.main_process_leads --client configs/<client>.local.yaml --lead-id L001 --write

# 5. Write small batch only after the one-row write is verified
python -m groot_ops.main_process_leads --client configs/<client>.local.yaml --limit 3 --write
```

Verify the Google Sheet after each write:

- Lead score and temperature updated
- Draft message present
- Approval status is `needs_approval` or `blocked`
- `updated_at` and `last_run_id` populated
- Activity Log row appended

## Cron examples for Phase 2

Do not enable these until a pilot client approves scheduled automation.

```cron
# Process new/changed leads every hour during business hours, weekdays.
0 9-17 * * 1-5 cd /opt/data/groot-ops && set -a && . ./.env && set +a && .venv/bin/python -m groot_ops.main_process_leads --client configs/<client>.local.yaml --write >> logs/<client>-process.log 2>&1

# Send owner summary email each morning through Maton Gmail.
30 8 * * 1-5 cd /opt/data/groot-ops && set -a && . ./.env && set +a && .venv/bin/python -m groot_ops.main_daily_summary --client configs/<client>.local.yaml --email-owner --to "$GROOT_OPS_OWNER_EMAIL" >> logs/<client>-summary.log 2>&1
```

## Hermes cron recommendation

For Rex's pilot, prefer Hermes cron over raw system cron so failures can be delivered back to the operator chat. The cron prompt should be self-contained and should run one command only, then report:

- Client name
- Command run
- Number of leads processed or summary counts
- Any error output
- Whether writes were enabled
- Whether owner email delivery was enabled and the recipient source (`GROOT_OPS_OWNER_EMAIL`, config owner destination, or explicit `--to` override)

Production email checklist:

1. `MATON_API_KEY` is present in the runtime/deployment environment.
2. Maton has an active `google-mail` connection.
3. `GROOT_OPS_OWNER_EMAIL` is set for Hermes cron wrappers, or the client config has `notifications.owner_channel: email` and `notifications.owner_destination`.
4. Manual verification succeeds:

```bash
/opt/data/scripts/groot-ops-phase2a-daily-summary.sh
# Expected final line includes: Owner email sent for <owner email>
```

## Rollback

If a write-mode run updates the wrong rows:

1. Stop scheduled jobs immediately.
2. Export or copy the current Sheet for evidence.
3. Restore from Google Sheets version history or undo manually.
4. Review Activity Log entries for the `last_run_id`.
5. Re-run dry-run with `--lead-id` before any new write.
