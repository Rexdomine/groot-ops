# Client Onboarding Checklist

Use this checklist to configure a new real estate client for the Phase 1 MVP.

## Business profile

- Business / brokerage name
- Primary agent name
- Agent phone number
- Agent email address
- Timezone
- Preferred messaging voice
- Required compliance or opt-out text

## Lead source setup

- Export current leads to the sheet schema in `docs/sheet_schema.md`
- Confirm lead source labels (website, Zillow, referral, open house, etc.)
- Confirm which fields are required for qualification
- Confirm stale lead threshold and follow-up expectations

## Approval workflow

- Identify who reviews draft messages
- Agree that Phase 1 does not send messages automatically
- Define allowed approval statuses: blank, `needs_approval`, `approved`, `rejected`, `blocked`

## Demo validation

- Run lead processing without `--write` first; dry-run is the default
- Use `--write` only after reviewing dry-run output
- Review hot/warm/cold/needs_info classifications
- Review draft tone and compliance footer
- Run daily summary and verify counts

## Config path conventions

- Relative `repository.leads_csv` and `repository.activity_log_csv` paths are resolved from the YAML config file directory.
- For configs under `configs/`, use paths like `../data/client_leads.csv` to reference repo-level data files.

## Google Sheets pilot setup

- Add `Leads` and `Activity Log` tabs using `docs/sheet_schema.md`
- Copy `configs/client.example.yaml` or `configs/pilot_realtor.example.yaml` to `configs/<client>.local.yaml`
- Fill only non-secret placeholders in the config; keep private sheet IDs and client-specific files untracked when appropriate
- For Rex/Hermes pilots, use `repository.credentials_env: MATON_API_KEY`
- For native Google access, create a Google Cloud project and service account outside this repo, then share the Sheet with the service account email
- Store credentials outside git; use `repository.credentials_env` or `repository.service_account_file`
- Follow `docs/google_sheets_setup.md` before running pilot write mode

## Phase 1.5 production readiness gate

Before Phase 2 scheduling or a real client pilot:

- Run `python -m pytest -q`
- Run `python scripts/production_readiness_check.py`
- Confirm `.env`, service-account JSON, and `configs/*.local.yaml` are not staged
- Run the pilot-safe sequence: daily summary, one-row dry-run, small-batch dry-run, one-row write, small-batch write
- Confirm Activity Log rows are appended only in write mode
- Confirm the client understands that Phase 1.5 creates drafts/recommendations only and does not auto-send messages
