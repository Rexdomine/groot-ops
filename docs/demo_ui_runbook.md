# Groot Ops Lightweight Demo UI Runbook

## Purpose

This UI is a guided demo console for real estate agents. It shows how simple Groot Ops is to configure without turning the pilot into a full SaaS platform too early.

## What the demo UI does

- Lets a user create a Groot Ops account with email/password.
- Uses server-side sessions with an HttpOnly cookie for `/setup`, `/dashboard`, and `/clients/*`.
- Collects business profile details.
- Accepts a Google Sheet URL or spreadsheet ID.
- Records owner notification preferences.
- Records automation scoring and message-tone rules.
- Validates Google Sheet access where credentials are configured.
- Previews daily owner summaries.
- Previews lead follow-up drafts in dry-run mode.
- Lets the operator click **Mark pilot active** after previews look good. This marks the saved config active while keeping the no-customer-auto-send safety boundary. Recurring runs still require the operator scheduler/Hermes cron.

## What it does not do yet

- It does not send customer-facing SMS, WhatsApp, or email.
- It does not auto-create Hermes cron jobs.
- It does not store API keys in config files.
- It does not replace the realtor’s CRM.
- It does not yet provide email verification, password reset, change-password, or logout-all-sessions flows; those are Phase 3.
- It does not yet persist user-owned client configs/dashboards in Neon; that is Phase 4.

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
http://127.0.0.1:8080/signup
```

Create an account, then use `/setup` and `/dashboard` normally. Anonymous access to `/setup`, `/dashboard`, and `/clients/*` redirects to `/login?next=...`.

## Required environment variables

For live Google Sheets validation and previews through Maton:

```bash
export MATON_API_KEY=...
```

For Vercel, add this as a project environment variable for every environment you use. Preview deployments and Production deployments have separate scopes; if the key was added only to Preview, the dashboard will show it as missing immediately after a PR is merged to Production.

```bash
vercel env add MATON_API_KEY production
vercel env add MATON_API_KEY preview
```

For Neon-backed auth/session readiness:

```bash
vercel env add DATABASE_URL production
vercel env add DATABASE_URL preview
vercel env add DATABASE_URL_UNPOOLED production
vercel env add DATABASE_URL_UNPOOLED preview
vercel env add GROOT_OPS_DB_CONNECT_TIMEOUT production
vercel env add GROOT_OPS_DB_CONNECT_TIMEOUT preview
```

`GROOT_OPS_DASHBOARD_TOKEN` is obsolete for normal user routes. Do not add it for new environments and do not include `?token=` links in setup, dashboard, or owner email flows.

## Vercel deployment shape

The repo includes:

- `api/index.py` — Vercel Python entrypoint.
- `vercel.json` — routes all web traffic to the FastAPI app.
- `requirements.txt`, `pyproject.toml`, and `uv.lock` — dependencies Vercel installs.

Deploy flow once Vercel access is connected:

```bash
vercel link
vercel env add MATON_API_KEY production
vercel env add MATON_API_KEY preview
vercel env add DATABASE_URL production
vercel env add DATABASE_URL preview
vercel env add DATABASE_URL_UNPOOLED production
vercel env add DATABASE_URL_UNPOOLED preview
vercel env add GROOT_OPS_DB_CONNECT_TIMEOUT production
vercel env add GROOT_OPS_DB_CONNECT_TIMEOUT preview
vercel deploy
```

For production aliasing later:

```bash
vercel deploy --prod
```

For protected Preview QA, keep Vercel Deployment Protection enabled and use Vercel’s official automation protection bypass secret/header for scripted checks. Never commit or log the bypass secret.

## 5-minute realtor demo script

1. Open the homepage.
2. Say: “Groot Ops works with the Google Sheet you already use.”
3. Click **Create account** or **Start setup**.
4. Create/login to a Groot Ops account.
5. Fill in the brokerage/agent details.
6. Paste the Google Sheet URL.
7. Choose Telegram or email as the owner notification preference.
8. Keep default automation rules.
9. Click **Save setup & validate sheet**.
10. Open the dashboard.
11. Run **Daily summary preview**.
12. Run **Preview lead drafts**.
13. Explain: “No customer messages are sent automatically. You stay in control. Groot identifies the hot leads and drafts the follow-up.”
14. Click **Mark pilot active** once the previews look right.
15. Close with: “The pilot config is now marked active. We enable the operator scheduler separately when you approve recurring runs.”

## Troubleshooting

### `MATON_API_KEY is not configured`

The UI can save setup, but live sheet validation/previews need the Maton API key in the environment. Vercel separates environment variables by deployment target. If this appears after merging a PR, the most likely root cause is that `MATON_API_KEY` exists for Preview but not Production. Add it to Production, then redeploy.

### `Could not read leads yet`

Check:

- Spreadsheet ID is correct.
- The connected Google account can access the sheet.
- Leads sheet is named `Leads` or matches the configured sheet name.
- Required columns exist.

### Vercel notes

Serverless files are ephemeral. Demo configs are written to `/tmp/groot-ops-demo-configs` on Vercel unless `GROOT_OPS_DEMO_CONFIG_DIR` is set. This is acceptable for the lightweight demo. Persistent user-owned multi-client storage is Phase 4.

### Redirected to login

This is expected when no valid Groot Ops session cookie is present. Login at `/login`; after successful login the app returns to the protected `next` URL when it is safe.
