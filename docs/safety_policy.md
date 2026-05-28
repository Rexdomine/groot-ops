# Safety Policy

Groot Ops Phase 1.5 is a human-in-the-loop lead follow-up assistant. It can score leads, draft suggested follow-up copy, update internal control sheets, and generate owner summaries. It must not send customer-facing messages automatically in this phase.

## Non-negotiable rules

- No automatic outbound messages to leads, customers, partners, or vendors.
- Drafts are internal recommendations until a human approves and manually sends them outside Groot Ops.
- Never commit API keys, OAuth tokens, service-account JSON, `.env`, private keys, or client-only configs.
- Treat lead names, emails, phone numbers, budgets, and messages as confidential client data.
- Use dry-run first for every new client, new sheet, schema change, or scoring change.
- Use `--lead-id` or `--limit` for the first write-mode pilot runs.
- Record write-mode processing in the configured Activity Log.

## Approval gate

Generated draft messages should be marked `needs_approval` when valid. A future sender may only send if all of these are true:

- `approval_status` is exactly `approved`
- `draft_message` is present
- The approved draft text has not changed since approval
- The lead has not already been sent the same message
- The client has explicitly enabled outbound sending for that channel

If automation regenerates or changes a draft, approval must reset to `needs_approval` and approval/send metadata must be cleared.

## Dry-run and write mode

Dry-run is the default for `groot_ops.main_process_leads`. It may read Sheets/CSV files and print proposed changes, but must not update rows or append Activity Log events.

Write mode requires explicit `--write`. Operators must review dry-run output before using write mode.

## Error handling and escalation

A lead should be surfaced for manual cleanup when required information is missing or invalid, including:

- Missing phone/email contact path
- Missing budget or location
- Missing or unclear timeline
- Draft validation failure
- Spreadsheet/API authentication failure

Failed production runs should alert the operator with client name, command/job name, failure reason, and suggested next action.

## Phase boundary

Phase 1.5 ends with a safe, repeatable pilot system. Phase 2 may add scheduled runs and real client pilots. Outbound sending remains out of scope until Rex explicitly approves a sender design with duplicate-send prevention, audit logs, and per-client opt-in controls.
