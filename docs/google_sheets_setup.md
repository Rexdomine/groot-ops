# Google Sheets Pilot Setup

Phase 1.5 supports a Google Sheets-backed repository behind the same lead repository interface as CSV. It is still safety-first: dry-run is the default, `--write` is required for updates, and Groot Ops does **not** send SMS, email, WhatsApp, or Gmail messages.

## 1. Prepare the spreadsheet

Create a Google Sheet with two tabs:

- `Leads`: lead control center using the columns in `docs/sheet_schema.md`
- `Activity Log`: append-only log; recommended header is `timestamp,event_type,lead_id,message`

Share the spreadsheet with the Google service account email as Editor.

## 2. Configure credentials outside git

Use one of these non-secret config references:

- `repository.credentials_env`: env var containing either service-account JSON or a path to a service-account JSON file
- `repository.service_account_file`: path to a service-account JSON file; supports env expansion such as `${GOOGLE_APPLICATION_CREDENTIALS}`

Never commit service-account JSON, `.env`, or downloaded credentials.

Example environment:

```bash
export GROOT_GOOGLE_SERVICE_ACCOUNT_JSON=/secure/path/groot-pilot-service-account.json
# or
export GOOGLE_APPLICATION_CREDENTIALS=/secure/path/groot-pilot-service-account.json
```

## 3. Create a pilot config

Copy `configs/pilot_realtor.example.yaml` to a client-specific file that is not secret-bearing. Replace placeholders:

```yaml
repository:
  type: google_sheets
  spreadsheet_id: YOUR_SPREADSHEET_ID
  leads_sheet: Leads
  activity_log_sheet: Activity Log
  credentials_env: GROOT_GOOGLE_SERVICE_ACCOUNT_JSON
```

The config must not contain credential JSON or private keys.

## 4. Install optional Google dependencies

The test suite uses mocked clients and does not require Google packages. Live Google Sheets access requires:

```bash
pip install google-api-python-client google-auth
```

## 5. Run safely

Dry-run one row first:

```bash
PYTHONPATH=src python -m groot_ops.main_process_leads --client configs/pilot_realtor.yaml --lead-id L001
```

Dry-run a small batch:

```bash
PYTHONPATH=src python -m groot_ops.main_process_leads --client configs/pilot_realtor.yaml --limit 3
```

Write mode is explicit:

```bash
PYTHONPATH=src python -m groot_ops.main_process_leads --client configs/pilot_realtor.yaml --lead-id L001 --write
```

Daily summary works through the repository abstraction:

```bash
PYTHONPATH=src python -m groot_ops.main_daily_summary --client configs/pilot_realtor.yaml
```

## 6. Manual approval and sending policy

Groot Ops only drafts and queues messages. The operator must review the Sheet, manually approve if appropriate, and manually send outside the system.

- Valid generated drafts are marked `needs_approval`.
- Invalid drafts are marked `blocked` with `errors`.
- If a previously approved draft changes, approval returns to `needs_approval` and approval/send metadata is cleared.
- No outbound sending is implemented in this repo.
