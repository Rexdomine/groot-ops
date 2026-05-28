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

- Create a Google Cloud project and service account outside this repo
- Share the Google Sheet with the service account
- Add `Leads` and `Activity Log` tabs using `docs/sheet_schema.md`
- Copy `configs/pilot_realtor.example.yaml` and fill only non-secret placeholders
- Store credentials outside git; use `repository.credentials_env` or `repository.service_account_file`
- Follow `docs/google_sheets_setup.md` before running pilot write mode
