# Groot Ops — Project Handoff Checkpoint

Last updated: 2026-06-18

## Read first when resuming

When returning to Groot Ops, read these files before implementation:

1. `docs/POC_SYSTEM_DESIGN.md` — locked Stable PoC architecture and constraints.
2. `docs/plans/2026-06-18-stable-poc-auth-neon-rollout.md` — phase-by-phase build plan.
3. `docs/safety_policy.md` — existing safety rules around customer-facing outreach.

## Project identity

Groot Ops is an AI operations automation service for small businesses, currently implemented as a real-estate lead follow-up and owner-summary pilot system.

Repository path:

- `/opt/data/groot-ops`

GitHub remote:

- `https://github.com/Rexdomine/groot-ops.git`

Canonical PoC/prod URL:

- `https://groot-ops.vercel.app`

## Locked Stable PoC decision

Rex approved the Stable PoC system design on 2026-06-18.

The direction is now locked as:

```text
Vercel free hosting
+ Vercel-provided domain: https://groot-ops.vercel.app
+ Neon Postgres free database
+ custom app-owned authentication
+ secure HttpOnly server-side sessions
+ Google Sheets as the lead source of truth
+ Maton/Gmail for low-volume PoC emails
+ no customer-facing auto-send during PoC
```

Do not move to Render free for the PoC unless Rex explicitly reopens the architecture decision. Render free web services can sleep after idle time, and Render free Postgres expires after 30 days. The chosen free database for the PoC is Neon Postgres.

Do not purchase or require a custom domain for PoC. The Vercel-provided domain is acceptable for early testers.

Do not use hosted third-party auth as the main PoC auth provider. Build custom auth in the app.

Do not use pure stateless JWT as the primary browser dashboard auth. Use opaque random session tokens in secure HttpOnly cookies, with only hashed session tokens stored in Neon. JWT may be added later for APIs/mobile/integrations if needed.

## Stable PoC architecture summary

```text
User
  ↓
https://groot-ops.vercel.app
  ↓
Vercel-hosted FastAPI/Jinja app
  ↓
Custom authentication
  - signup
  - login
  - logout
  - account/session management
  - password reset
  - email verification
  ↓
Neon Postgres
  - users
  - sessions
  - auth tokens
  - client/business profiles
  - client configs
  - automation run metadata
  - audit events
  ↓
Groot Ops core
  - Google Sheet validation
  - lead scoring
  - follow-up draft generation
  - approval queue
  - owner daily summary
  ↓
Maton/Gmail for low-volume emails
```

## Neon free-plan assumptions supplied by Rex

- `$0`
- no time limit
- no credit card required
- 100 projects
- 100 CU-hours monthly per project
- 0.5 GB storage per project
- sizes up to 2 CU / 8 GB RAM
- Neon Auth: 60K MAUs available but not used as primary auth
- 6-hour time travel/restores
- autoscaling, branching, read replicas
- unlimited team members

Storage discipline: store app/account/config/run metadata in Neon, not full lead history. Keep actual leads and detailed activity rows in the user’s Google Sheets during the PoC.

## Current phase tracker

### Phase 0 — Planning lock and repo hygiene

Status: **completed**

Done:

- locked Stable PoC architecture in `docs/POC_SYSTEM_DESIGN.md`;
- created implementation plan at `docs/plans/2026-06-18-stable-poc-auth-neon-rollout.md`;
- updated this checkpoint;
- committed planning docs in `82c7292 docs: lock stable poc architecture`;
- added `configs/demo_clients/` to `.gitignore` so local demo/source-of-truth configs stay local and do not enter PRs.

### Phase 1 — Neon database foundation

Status: **completed**

Done:

- added Postgres runtime dependency (`psycopg[binary]`);
- added `src/groot_ops/db.py` for safe DB URL handling, credential-redacted DB labels, configurable-timeout DB connections, and readiness checks;
- added migration runner at `scripts/apply_migrations.py` with dry-run support and local `.env` loading;
- added first migration at `migrations/001_auth_and_clients.sql`;
- created live Neon tables for users, sessions, verification/reset tokens, login attempts, clients, client configs, automation runs, audit events, and migration tracking;
- added `/ready` endpoint that checks DB connectivity without exposing credentials;
- updated `.env.example` with safe placeholder `DATABASE_URL` and `NEON_API_KEY` fields;
- configured Vercel/Vasio project env for Phase 1 DB runtime: `DATABASE_URL`, `DATABASE_URL_UNPOOLED`, and `GROOT_OPS_DB_CONNECT_TIMEOUT=5` exist for Production, Development, and the PR #15 Preview branch;
- verified live Neon schema and local `/ready` response;
- hosted Vercel Preview originally reached the app but returned `database.status=connection_failed`; root cause was `uv.lock` missing `psycopg`, so Vercel installed from a stale lock without the DB driver even though `requirements.txt` and `pyproject.toml` were updated;
- updated `uv.lock` to include `psycopg`/`psycopg-binary` so Vercel installs the Phase 1 DB runtime dependency;
- added safe server-side DB readiness logging so future Vercel logs reveal the exception class without exposing credentials;
- redeployed a fresh Vercel Preview from the corrected lockfile and verified hosted `/ready` returns `status=ready` and `database.status=ok`;
- ran full tests and production readiness check: `69 passed, 1 warning`; readiness passed.

### Phase 2 — Custom authentication core

Status: **in progress on `feat/phase2-custom-auth`**

Done locally:

- added `src/groot_ops/auth.py` with PBKDF2 password hashing, opaque random session tokens, SHA-256 session-token storage, login-attempt recording, and Neon-backed user/session operations;
- added `/signup`, `/login`, and `/logout` routes with HttpOnly SameSite=Lax session cookies;
- replaced the old dashboard token wall for `/setup`, `/dashboard`, and `/clients/*` with session middleware and login redirects that preserve `next`;
- updated home/header CTA behavior for anonymous vs authenticated users;
- added login/signup templates and styles;
- updated tests so old `/setup?token=...` links no longer grant access;
- verified local test suite: `77 passed, 1 warning`;
- verified production readiness check and migration dry-run;
- verified live Neon auth smoke using a throwaway user/session and cleaned it up.

Hosted verification completed:

- Phase 2 PR: https://github.com/Rexdomine/groot-ops/pull/16
- Vercel Preview: `https://groot-dn6hfx5f0-rexdomines-projects.vercel.app`
- `/ready` returned `status=ready` and `database.status=ok`.
- Anonymous `/setup` redirects to `/login?next=%2Fsetup`.
- Hosted `/signup` creates a secure HttpOnly session and redirects to `/setup`.
- Authenticated `/setup` renders `Setup Health`, the logged-in user, and logout control.
- Hosted `/logout` revokes the session and redirects to `/login?logged_out=1`.
- The same session is blocked from `/setup` after logout.
- Hosted QA used Vercel's official automation protection bypass header for Preview testing; the bypass secret is not committed or logged.
- Throwaway hosted test user/session was cleaned from Neon after verification.

Remaining before completion:

- run NightWing QA;
- report PR checks/preview status.

### Phase 3 — Account recovery and verification

Status: **not started**

Goal:

- email verification, forgot/reset password, change password, logout all sessions.

### Phase 4 — Dashboard persistence and ownership

Status: **not started**

Goal:

- save setup to Neon, load dashboard from Neon, tie dashboard/client records to authenticated user ownership.

### Phase 5 — Admin/operator controls

Status: **not started**

Goal:

- admin role, admin users/clients pages, disable account, revoke sessions, trigger reset email, view run status.

### Phase 6 — Production hardening and observability

Status: **not started**

Goal:

- CSRF, DB-backed auth rate limiting, security headers, cleanup command, audit/event hygiene.

### Phase 7 — Pilot QA and Vercel deployment

Status: **not started**

Goal:

- final production deploy/alias promotion, QA full signup/login/setup/dashboard flow, and confirm every phase-dependent Vercel/Vasio env var or external-service config is present before marking the phase complete.

## Existing Phase 1.5 foundation before Stable PoC upgrade

The system already can:

- read leads from CSV or Google Sheets;
- score leads as hot, warm, cold, or needs_info;
- generate safe follow-up draft copy;
- place drafts behind a human approval gate;
- produce daily owner summaries;
- update sheet/log fields in explicit write mode;
- run in safe dry-run mode by default;
- validate pilot setup through a lightweight FastAPI/Jinja UI;
- deploy to Vercel through `api/index.py` and `vercel.json`;
- send owner-facing setup and summary emails through Maton Gmail when configured.

Existing current problem addressed by Phase 2:

- normal `Start Setup` / `View Dashboard` flow no longer uses the dashboard-token access wall;
- early users can use normal signup/login and server-side sessions;
- persistent user-owned dashboards are still Phase 4.

## Current branch/state at latest inspection

Current local branch when checkpointed:

- `feat/phase2-custom-auth`

Remote tracking branch:

- not pushed yet at this checkpoint

Current branch contains Phase 2 auth work beyond `origin/main`:

- app-owned signup/login/logout/session auth;
- removed token wall from normal user routes;
- tests/docs/env-template updates.

Untracked local demo configs should remain local/ignored and must not enter PRs.

## Production/deployment notes

Local `.env` contains required deployment/runtime secrets, but secrets must not be printed or committed.

Known local/deployment env keys used when checked:

- `VERCEL_TOKEN`
- `MATON_API_KEY`
- `DATABASE_URL`
- `DATABASE_URL_UNPOOLED`
- `GROOT_OPS_DB_CONNECT_TIMEOUT`

Legacy note:

- `GROOT_OPS_DASHBOARD_TOKEN` may still exist in old local/Vercel environments, but Phase 2 does not use it for normal user routes or owner email links.

Use the Rex-specific deployment route:

```bash
cd /opt/data/groot-ops
set -a
. ./.env
set +a
npx vercel --prod --yes --token "$VERCEL_TOKEN"
```

## Current code map

Core files:

- `src/groot_ops/config_loader.py` — loads and validates client YAML.
- `src/groot_ops/models.py` — `ClientConfig` and `Lead` data models.
- `src/groot_ops/csv_repository.py` — local CSV repository adapter.
- `src/groot_ops/google_sheets_repository.py` — Google Sheets repository with Maton/native support.
- `src/groot_ops/repository_factory.py` — repository/activity recorder factory.
- `src/groot_ops/lead_scorer.py` — deterministic lead scoring.
- `src/groot_ops/message_drafter.py` — safe template-based follow-up drafts.
- `src/groot_ops/approval_queue.py` — approval gate and send-eligibility guard.
- `src/groot_ops/daily_summary.py` — owner summary buckets and formatting.
- `src/groot_ops/main_process_leads.py` — CLI for scoring/drafting leads.
- `src/groot_ops/main_daily_summary.py` — CLI for daily summary and optional owner email.
- `src/groot_ops/ui_config_service.py` — UI setup parsing, validation, YAML writing.
- `src/groot_ops/ui_app.py` — FastAPI setup/dashboard app.
- `src/groot_ops/owner_notifications.py` — branded owner setup/summary emails via Maton Gmail.
- `api/index.py` — Vercel Python serverless entrypoint.
- `vercel.json` — all routes go to the FastAPI app.

## Safety rules

Default operation is dry-run. Write mode requires `--write`.

Before a pilot write run, use this order:

1. read-only summary;
2. dry-run one row;
3. dry-run small batch;
4. write one row;
5. write small batch only after verification.

No customer-facing sending is implemented or allowed in Stable PoC. Future outbound sending must require:

- `approval_status=approved`;
- non-empty `draft_message`;
- duplicate-send prevention;
- explicit client opt-in for the channel;
- exact approved draft text unchanged;
- separate explicit design/review phase.

## Last verification before Stable PoC planning (historical pre-Phase 1 state)

Commands run:

```bash
python -m pytest -q
python scripts/production_readiness_check.py
```

Result:

- `51 passed, 1 warning`
- `Production readiness static check passed.`

Public deployment checks:

- `https://groot-ops.vercel.app/health` => `200`
- `https://groot-ops.vercel.app/` => `200`, landing page title `Groot Ops — AI Lead Follow-Up for Real Estate`
- `https://groot-ops.vercel.app/setup` without token => `401`, protected dashboard access required
- `https://groot-ops.vercel.app/dashboard` without token => `401`, protected dashboard access required

## Immediate next steps when resuming

1. Run `git status --short --branch`.
2. Review planning docs and ensure no secrets are present.
3. Decide whether to commit planning docs on current branch.
4. Resolve or intentionally leave the untracked demo client config.
5. Begin Phase 1 from `docs/plans/2026-06-18-stable-poc-auth-neon-rollout.md`.
