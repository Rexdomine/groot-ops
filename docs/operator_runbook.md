# Operator Runbook

## Daily dry-run lead processing

```bash
cd /opt/data/groot-ops
PYTHONPATH=src python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml --dry-run
```

`--dry-run` is optional because dry-run is the default.

Review each printed lead:

- Score and temperature
- Recommended action
- Draft message
- Approval status
- Errors / missing fields

Dry-run does not write to the CSV or activity log.

## Write-mode processing

Only use write mode after reviewing dry-run output:

```bash
PYTHONPATH=src python -m groot_ops.main_process_leads --client configs/sample_realtor.yaml --write
```

Write mode updates lead scoring, draft fields, approval queue fields, and `data/activity_log.csv`.

## Daily summary

```bash
PYTHONPATH=src python -m groot_ops.main_daily_summary --client configs/sample_realtor.yaml
```

The summary reports:

- New leads
- Hot leads
- Follow-ups due
- Pending approvals
- Stale leads
- Errors / records needing cleanup

## Approval policy

No outbound sending is implemented in Phase 1. If a future sender is added, it must call `is_send_eligible(lead)` and only proceed when:

- `approval_status` is `approved`
- `draft_message` is present and non-empty

Approvals are tied to exact draft text. If processing regenerates a different `draft_message`, the row returns to `needs_approval` and approval/send metadata is cleared.

## Error handling

Records with missing phone, budget, location, or timeline are surfaced in `errors`. Fix the sheet fields, then rerun processing.
