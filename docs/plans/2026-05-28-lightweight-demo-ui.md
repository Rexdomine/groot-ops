# Lightweight Demo UI Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a lightweight Groot Ops demo UI that lets real estate agents understand and configure the lead follow-up automation in minutes.

**Architecture:** Add a simple local web app inside the existing Python repo. The UI writes/validates client configuration, previews Google Sheets setup, runs safe dry-runs, displays daily summary output, and shows automation status without sending customer-facing messages. Keep Google Sheets as the MVP control center and Hermes cron as the pilot runner.

**Tech Stack:** Python standard library or small FastAPI app, server-rendered HTML/CSS, existing `groot_ops` modules, YAML client configs, current Google Sheets/Maton repository adapter, pytest.

---

## Product Positioning

The demo must make agents feel: “I can set this up without being technical.”

The UI is not a full SaaS dashboard yet. It is a guided setup and demo console for a pilot automation package.

### Primary Demo Story

1. Agent enters business profile.
2. Agent connects or pastes Google Sheet details.
3. Agent chooses where owner notifications should go.
4. Agent reviews lead scoring/follow-up preferences.
5. Groot Ops validates the setup.
6. Agent runs a safe preview on sample/current leads.
7. Agent sees a daily summary and drafted follow-ups.
8. Rex explains: “This can now run automatically for you every weekday.”

## Recommended UX: 5-Step Setup Wizard

### Step 1: Business Profile

Fields:
- Business/Brokerage name
- Agent name
- Agent email
- Agent phone
- Timezone

UX copy:
- “Tell Groot Ops who this automation is working for.”

Writes to:
- `client_id`
- `business_name`
- `agent_name`
- `agent_email`
- `agent_phone`
- `timezone`

### Step 2: Lead Source

Fields:
- Google Sheet URL or spreadsheet ID
- Leads sheet name, default `Leads`
- Activity log sheet name, default `Activity Log`
- Connection method display: `Connected through secure Google access`

UX features:
- Parse spreadsheet ID from pasted Google Sheet URL.
- Show required columns checklist.
- Button: “Validate Sheet”
- Validation result: green/yellow/red status.

Writes to:
- `repository.type: google_sheets`
- `repository.spreadsheet_id`
- `repository.leads_sheet`
- `repository.activity_log_sheet`
- `repository.credentials_env: MATON_API_KEY` for Rex/Hermes pilots

### Step 3: Notifications

Fields for demo:
- Owner notification channel: Telegram, Email, WhatsApp placeholder
- Destination label/handle/email
- Daily summary time
- Lead processing frequency

Important MVP boundary:
- For Phase 2A, the UI records preferences and shows the schedule, but actual Hermes cron creation remains operator-controlled unless Rex approves UI-triggered scheduling.

Writes to new config section later:
- `notifications.owner_channel`
- `notifications.owner_destination`
- `schedule.daily_summary_time`
- `schedule.process_leads_frequency`

### Step 4: Automation Rules

Fields:
- Hot lead timeline, default 14 days
- Warm lead timeline, default 60 days
- Stale lead threshold, default 7 days
- Message tone, default friendly/concise/professional
- Max draft length, default 700 chars
- Required opt-out disclaimer

UX copy:
- “These rules tell Groot Ops how to rank and draft follow-up for leads.”

Writes to existing sections:
- `scoring.*`
- `messaging.*`
- `summary.*`

### Step 5: Preview & Activate

Cards:
- Setup health
- Latest daily summary preview
- Lead processing preview
- Safety boundary: “No customer messages are sent automatically.”
- Next operator step: “Rex activates weekday automation after approval.”

Buttons:
- “Run Daily Summary Preview” → calls existing read-only summary command/module.
- “Preview 3 Leads” → calls processor without `--write`.
- “Write Internal Updates for 3 Leads” → optional protected demo action; requires confirmation.

## Demo Dashboard After Setup

Keep this single-page and visual:

### Cards

- New leads today
- Hot leads
- Needs approval
- Stale leads
- Last run status

### Sections

1. **Today’s Owner Summary**
   - Render output from `main_daily_summary`.

2. **Lead Queue**
   - Lead name
   - Temperature: hot/warm/cold
   - Recommended action
   - Draft status
   - Approval status

3. **Draft Preview**
   - Click a lead to view generated draft copy.
   - Label clearly as draft.

4. **Activity Log**
   - Recent automation actions from Activity Log.

5. **Automation Schedule**
   - Daily summary time
   - Processing frequency
   - Delivery destination
   - Status: demo/manual/Hermes active

## File/Code Plan

### Task 1: Add web app dependency decision

**Objective:** Decide between zero-dependency standard library and FastAPI.

Recommended choice: FastAPI + Jinja2 only if acceptable; otherwise Python stdlib `http.server` can work but becomes clunky for forms. For demo quality, choose FastAPI/Jinja2.

Modify:
- `pyproject.toml`

Add optional dependency group:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0"]
sheets = ["google-api-python-client>=2.0", "google-auth>=2.0"]
ui = ["fastapi>=0.115", "uvicorn>=0.30", "jinja2>=3.1", "python-multipart>=0.0.9"]
```

Verification:
- `python -m pip install -e '.[ui,dev]'`
- `pytest`

### Task 2: Extend config model for UI preferences

**Objective:** Support notification and schedule preferences without breaking existing config loading.

Modify:
- `src/groot_ops/models.py`
- `src/groot_ops/config_loader.py`
- `tests/test_config_loader.py`

Add optional fields to `ClientConfig`:
- `owner_notification_channel: str = "telegram"`
- `owner_notification_destination: str = ""`
- `daily_summary_time: str = "08:30"`
- `process_leads_frequency: str = "every_2h_weekdays"`
- `automation_status: str = "demo_manual"`

Verification:
- Existing tests still pass.
- New test confirms old configs load with defaults.
- New test confirms new notification/schedule sections load.

### Task 3: Add UI config service

**Objective:** Separate form parsing, validation, and YAML writing from route handlers.

Create:
- `src/groot_ops/ui_config_service.py`
- `tests/test_ui_config_service.py`

Functions:
- `parse_spreadsheet_id(value: str) -> str`
- `slugify_client_id(business_name: str, agent_name: str) -> str`
- `build_client_config_dict(form: dict[str, str]) -> dict`
- `write_client_config(path: Path, data: dict) -> None`
- `validate_setup(config: ClientConfig) -> list[SetupCheck]`

Safety:
- Write only under `configs/demo_clients/` by default.
- Never write secrets into YAML.
- Use `credentials_env: MATON_API_KEY`.

### Task 4: Add FastAPI app routes

**Objective:** Provide wizard and dashboard routes.

Create:
- `src/groot_ops/ui_app.py`
- `src/groot_ops/templates/base.html`
- `src/groot_ops/templates/setup.html`
- `src/groot_ops/templates/dashboard.html`
- `src/groot_ops/static/styles.css`

Routes:
- `GET /` → redirect or landing page
- `GET /setup` → setup wizard form
- `POST /setup` → save config, show validation results
- `GET /clients/{client_id}/dashboard` → dashboard
- `POST /clients/{client_id}/preview-summary` → run summary preview
- `POST /clients/{client_id}/preview-leads` → dry-run lead preview

Verification:
- Route tests with FastAPI TestClient.
- No customer-facing sending routes.

### Task 5: Add command to launch UI

**Objective:** Make demo easy for Rex.

Create:
- `src/groot_ops/main_ui.py`

Command:

```bash
python -m groot_ops.main_ui --host 127.0.0.1 --port 8080
```

Behavior:
- Starts uvicorn.
- Prints local URL.
- Defaults to local-only host for safety.

Verification:
- App boots.
- `/setup` returns 200.

### Task 6: Add sheet validation preview

**Objective:** Show the agent whether their Sheet is ready.

Use existing repository factory to read headers/leads.

Checks:
- Spreadsheet ID present
- Leads sheet reachable
- Required lead columns present
- Activity Log append path configured
- At least one lead row readable

UI result:
- Green: ready
- Yellow: can demo with warnings
- Red: cannot run yet

### Task 7: Add preview execution wrappers

**Objective:** Reuse existing automation modules from UI safely.

Create helpers:
- `run_daily_summary_preview(config_path: Path) -> str`
- `run_lead_preview(config_path: Path, limit: int = 3) -> str`

Rule:
- Default preview is dry-run only.
- Write mode requires a separate protected button and explicit confirmation text.

### Task 8: Add demo docs

**Objective:** Give Rex a repeatable sales demo script.

Create:
- `docs/demo_ui_runbook.md`

Include:
- How to install UI dependencies
- How to launch local UI
- 5-minute realtor demo script
- What to say about safety
- What to say about activation
- Troubleshooting checklist

## UI Design Direction

Visual style:
- Clean, bright, high-trust SaaS look.
- Not too technical.
- Green/blue accent for “automation is working.”
- Avoid developer terms like YAML, cron, environment variables in front of clients.

Suggested labels:
- “Lead Source” instead of repository.
- “Owner Notifications” instead of delivery target.
- “Automation Rules” instead of scoring config.
- “Preview Results” instead of dry-run.
- “Activate Pilot” instead of create cron.

## Safety Boundaries

Do not add automatic customer outbound sending in this UI yet.

The UI may:
- Save client setup config.
- Validate Google Sheet access.
- Run summaries.
- Preview lead processing.
- Optionally write internal lead scoring/draft fields if Rex confirms.

The UI must not:
- Send SMS/WhatsApp/email to leads.
- Create cron jobs without operator approval.
- Store API keys in config files.
- Expose private sheet IDs in public docs.

## MVP Acceptance Criteria

The demo UI is ready when Rex can:

1. Open a local web page.
2. Fill in a realtor profile.
3. Paste a Google Sheet URL.
4. Choose Telegram/email notification preference.
5. Validate the sheet.
6. Preview daily summary.
7. Preview 3 leads with draft follow-ups.
8. Explain that activation is a safe operator-controlled step.

## Later SaaS Path

After demos prove demand:

- Add login/auth.
- Add multi-client database instead of YAML files.
- Add OAuth self-service Google connection.
- Add Stripe billing.
- Add WhatsApp Business provider integration.
- Add approval/send workflow for outbound messages.
- Move from Hermes-managed pilot to VPS/Docker/queue-based service.
