# Groot Ops Lightweight Demo UI Runbook

## Purpose

This UI is a guided demo console for real estate agents. It shows how simple Groot Ops is to configure without turning the Phase 2A pilot into a full SaaS platform too early.

## What the demo UI does

- Collects business profile details.
- Accepts a Google Sheet URL or spreadsheet ID.
- Records owner notification preferences.
- Records automation scoring and message-tone rules.
- Validates Google Sheet access where credentials are configured.
- Previews daily owner summaries.
- Previews lead follow-up drafts in dry-run mode.

## What it does not do yet

- It does not send customer-facing SMS, WhatsApp, or email.
- It does not auto-create Hermes cron jobs.
- It does not store API keys in config files.
- It does not replace the realtor’s CRM.

## Local setup

Install UI dependencies:

```bash
uv run --extra ui --extra dev pytest
```

Run the UI locally:

```bash
uv run --extra ui python -m groot_ops.main_ui --host 127.0.0.1 --port 8080
```

Open:

```text
http://127.0.0.1:8080/setup
```

## Required environment variables

For live Google Sheets validation and previews through Maton:

```bash
export MATON_API_KEY=...
```

For Vercel, add this as a project environment variable.

## Vercel deployment shape

The repo now includes:

- `api/index.py` — Vercel Python entrypoint.
- `vercel.json` — routes all web traffic to the FastAPI app.
- `requirements.txt` — dependencies Vercel installs.

Deploy flow once Vercel access is connected:

```bash
vercel link
vercel env add MATON_API_KEY
vercel deploy
```

For production aliasing later:

```bash
vercel deploy --prod
```

## 5-minute realtor demo script

1. Open the homepage.
2. Say: “Groot Ops works with the Google Sheet you already use.”
3. Click **Start demo setup**.
4. Fill in the brokerage/agent details.
5. Paste the Google Sheet URL.
6. Choose Telegram or email as the owner notification preference.
7. Keep default automation rules.
8. Click **Save setup & validate sheet**.
9. Open the dashboard.
10. Run **Daily summary preview**.
11. Run **Preview lead drafts**.
12. Explain: “No customer messages are sent automatically. You stay in control. Groot identifies the hot leads and drafts the follow-up.”
13. Close with: “After you approve the setup, we activate weekday automation for you.”

## Troubleshooting

### `MATON_API_KEY is not configured`

The UI can save setup, but live sheet validation/previews need the Maton API key in the environment.

### `Could not read leads yet`

Check:

- Spreadsheet ID is correct.
- The connected Google account can access the sheet.
- Leads sheet is named `Leads` or matches the configured sheet name.
- Required columns exist.

### Vercel notes

Serverless files are ephemeral. Demo configs are written to `/tmp/groot-ops-demo-configs` on Vercel unless `GROOT_OPS_DEMO_CONFIG_DIR` is set. This is acceptable for a lightweight demo, but persistent multi-client storage should come later with a database or hosted config store.
