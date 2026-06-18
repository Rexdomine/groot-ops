# Groot Ops Stable PoC Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Convert Groot Ops from a protected pilot/demo dashboard into a stable no-cost PoC where early users can sign up, log in, configure their business, connect Google Sheets, and return to persistent dashboards.

**Architecture:** Keep the app on Vercel using the existing FastAPI/Jinja structure. Add Neon Postgres for durable user/client/config/session metadata. Replace token-only dashboard access with custom server-side session authentication using secure HttpOnly cookies and hashed session tokens stored in Neon.

**Tech Stack:** Python, FastAPI, Jinja templates, Vercel Python serverless, Neon Postgres, SQLAlchemy or psycopg, Alembic-style migrations or lightweight SQL migrations, Argon2id/bcrypt password hashing, Maton/Gmail for low-volume emails, pytest.

---

## Locked phase order

1. Phase 0 — Planning lock and repo hygiene
2. Phase 1 — Neon database foundation
3. Phase 2 — Custom authentication core
4. Phase 3 — Account recovery and verification
5. Phase 4 — Dashboard persistence and ownership
6. Phase 5 — Admin/operator controls
7. Phase 6 — Production hardening and observability
8. Phase 7 — Pilot QA and Vercel deployment

## Phase 0 — Planning lock and repo hygiene

**Status:** In progress at planning checkpoint.

**Objective:** Make the approved system design durable in the repo and prepare implementation safely.

### Task 0.1: Save locked system design

**Files:**
- Create: `docs/POC_SYSTEM_DESIGN.md`
- Modify: `PROJECT_HANDOFF_CHECKPOINT.md`

**Steps:**
1. Save the approved architecture and constraints.
2. Update checkpoint with the new current target.
3. Verify docs contain no secrets.

**Verification:**

```bash
grep -R "VERCEL_TOKEN\|MATON_API_KEY\|DATABASE_URL\|GROOT_OPS_DASHBOARD_TOKEN" docs/POC_SYSTEM_DESIGN.md PROJECT_HANDOFF_CHECKPOINT.md || true
```

Expected: no secret values. Mentioned env var names are acceptable; no values.

### Task 0.2: Review current branch and untracked config

**Files:**
- Inspect only initially.

**Steps:**
1. Run `git status --short --branch`.
2. Decide whether to keep, remove, gitignore, or sanitize `configs/demo_clients/rex_realty_pilot_mobile_dashboard_qa_princewill.yaml`.
3. Do not commit secrets.

**Verification:**

```bash
git status --short --branch
```

Expected: branch and untracked state understood before implementation.

---

## Phase 1 — Neon database foundation

**Objective:** Add durable Postgres persistence without changing user-facing behavior yet.

### Task 1.1: Add database dependency and settings

**Files:**
- Modify: `requirements.txt`
- Modify/Create: `src/groot_ops/settings.py` if needed
- Test: `tests/test_settings.py` or existing config tests

**Steps:**
1. Add Postgres driver/dependencies.
2. Add environment-based `DATABASE_URL` loading.
3. Keep app runnable without DB in legacy/local YAML mode until auth routes require DB.
4. Add tests for missing/present `DATABASE_URL` behavior.

**Verification:**

```bash
python -m pytest tests/test_config_loader.py tests/test_settings.py -q
```

Expected: relevant tests pass.

### Task 1.2: Create DB connection helper

**Files:**
- Create: `src/groot_ops/db.py`
- Test: `tests/test_db.py`

**Steps:**
1. Implement connection/session helper.
2. Ensure connections are opened/closed safely for Vercel serverless.
3. Prefer pooled/serverless-friendly Neon connection string when available.
4. Add testable function for DB readiness.

**Verification:**

```bash
python -m pytest tests/test_db.py -q
```

Expected: helper behavior passes with mocked DB URL/connection.

### Task 1.3: Add migration structure

**Files:**
- Create: `migrations/001_auth_and_clients.sql`
- Create: `scripts/apply_migrations.py`
- Test: `tests/test_migrations.py`

**Steps:**
1. Add SQL migration table, e.g. `schema_migrations`.
2. Add first migration for auth/client tables.
3. Add idempotent migration runner.
4. Add dry-run or test-mode coverage.

**Verification:**

```bash
python scripts/apply_migrations.py --dry-run
python -m pytest tests/test_migrations.py -q
```

Expected: migrations discovered and ordered correctly.

### Task 1.4: Create schema tables

**Files:**
- Modify: `migrations/001_auth_and_clients.sql`

**Tables:**
- `users`
- `sessions`
- `email_verification_tokens`
- `password_reset_tokens`
- `login_attempts`
- `clients`
- `client_configs`
- `automation_runs`
- `audit_events`

**Steps:**
1. Use UUID primary keys.
2. Use unique normalized email.
3. Use foreign keys for user/client ownership.
4. Store token hashes, never raw tokens.
5. Add useful indexes for sessions, tokens, and client lookups.

**Verification:**

```bash
python scripts/apply_migrations.py
```

Expected: migration applies to Neon/local test DB exactly once.

### Task 1.5: Add `/ready` endpoint

**Files:**
- Modify: `src/groot_ops/ui_app.py`
- Test: `tests/test_ui_app.py`

**Steps:**
1. Keep `/health` simple.
2. Add `/ready` to check DB connectivity and required production config.
3. Return safe JSON without secrets.

**Verification:**

```bash
python -m pytest tests/test_ui_app.py -q
curl -sS https://groot-ops.vercel.app/ready
```

Expected: tests pass locally; production endpoint after deployment reports readiness state safely.

---

## Phase 2 — Custom authentication core

**Objective:** Users can sign up, log in, log out, and access protected dashboard routes through secure sessions.

### Task 2.1: Add password hashing utility

**Files:**
- Create: `src/groot_ops/auth/passwords.py`
- Test: `tests/test_auth_passwords.py`

**Steps:**
1. Use Argon2id via a mature library if feasible.
2. Fallback to bcrypt only if Argon2 causes deployment issues.
3. Add `hash_password()` and `verify_password()`.
4. Add maximum password length guard to avoid DoS.

**Verification:**

```bash
python -m pytest tests/test_auth_passwords.py -q
```

Expected: hashes verify; wrong passwords fail; plaintext password is never returned.

### Task 2.2: Add auth repository

**Files:**
- Create: `src/groot_ops/auth/repository.py`
- Test: `tests/test_auth_repository.py`

**Steps:**
1. Implement create user.
2. Implement find by normalized email.
3. Implement create/revoke session.
4. Implement lookup session by hashed token.
5. Implement audit event creation.

**Verification:**

```bash
python -m pytest tests/test_auth_repository.py -q
```

Expected: repository stores and retrieves auth records correctly.

### Task 2.3: Add session cookie helpers

**Files:**
- Create: `src/groot_ops/auth/sessions.py`
- Test: `tests/test_auth_sessions.py`

**Steps:**
1. Generate high-entropy random session tokens.
2. Hash tokens before DB storage.
3. Set cookie with `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`.
4. Add expiry handling.

**Verification:**

```bash
python -m pytest tests/test_auth_sessions.py -q
```

Expected: cookie/session behavior matches security baseline.

### Task 2.4: Add signup route and template

**Files:**
- Modify: `src/groot_ops/ui_app.py`
- Create: `src/groot_ops/templates/signup.html`
- Test: `tests/test_auth_routes.py`

**Steps:**
1. Add GET `/signup`.
2. Add POST `/signup`.
3. Validate full name, email, password, confirm password.
4. Create user and session.
5. Redirect to `/setup`.
6. Use friendly UX and generic conflict messaging.

**Verification:**

```bash
python -m pytest tests/test_auth_routes.py::test_signup -q
```

Expected: signup creates user/session and redirects.

### Task 2.5: Add login route and template

**Files:**
- Modify: `src/groot_ops/ui_app.py`
- Create: `src/groot_ops/templates/login.html`
- Test: `tests/test_auth_routes.py`

**Steps:**
1. Add GET `/login`.
2. Add POST `/login`.
3. Verify password.
4. Create session on success.
5. Use generic failure message.
6. Redirect to `/dashboard` or `next` when safe.

**Verification:**

```bash
python -m pytest tests/test_auth_routes.py::test_login -q
```

Expected: valid login succeeds; invalid login fails generically.

### Task 2.6: Add logout route

**Files:**
- Modify: `src/groot_ops/ui_app.py`
- Test: `tests/test_auth_routes.py`

**Steps:**
1. Add POST `/logout`.
2. Revoke current session.
3. Clear cookie.
4. Redirect to `/login`.

**Verification:**

```bash
python -m pytest tests/test_auth_routes.py::test_logout -q
```

Expected: session revoked and cookie cleared.

### Task 2.7: Replace token wall on user routes

**Files:**
- Modify: `src/groot_ops/ui_app.py`
- Modify: templates containing Start Setup/View Dashboard links
- Test: `tests/test_ui_app.py`, `tests/test_auth_routes.py`

**Steps:**
1. `/setup` requires logged-in user, not dashboard token.
2. `/dashboard` requires logged-in user, not dashboard token.
3. Unauthenticated users redirect to `/login` with safe `next`.
4. Keep dashboard token only for legacy/internal support if still needed.

**Verification:**

```bash
python -m pytest tests/test_ui_app.py tests/test_auth_routes.py -q
```

Expected: normal users see login/signup instead of confusing dashboard-access wall.

---

## Phase 3 — Account recovery and verification

**Objective:** Add secure account lifecycle flows required for real testers.

### Task 3.1: Add email token utility

**Files:**
- Create: `src/groot_ops/auth/tokens.py`
- Test: `tests/test_auth_tokens.py`

**Steps:**
1. Generate random tokens.
2. Store only token hashes.
3. Add expiry checks.
4. Add one-time-use checks.

**Verification:**

```bash
python -m pytest tests/test_auth_tokens.py -q
```

Expected: token creation/verification/expiry works.

### Task 3.2: Add verification email flow

**Files:**
- Modify/Create: `src/groot_ops/auth/emails.py`
- Modify: `src/groot_ops/owner_notifications.py` if shared email sender is reused
- Create: `src/groot_ops/templates/verify_email_sent.html`
- Test: `tests/test_email_verification.py`

**Steps:**
1. Generate verification token after signup.
2. Send verification link through Maton/Gmail.
3. Add `/verify-email` route.
4. Add `/resend-verification` route with rate limiting.
5. Mark `email_verified_at`.

**Verification:**

```bash
python -m pytest tests/test_email_verification.py -q
```

Expected: verification marks account verified and token cannot be reused.

### Task 3.3: Add forgot/reset password flow

**Files:**
- Modify: `src/groot_ops/ui_app.py`
- Create: `src/groot_ops/templates/forgot_password.html`
- Create: `src/groot_ops/templates/reset_password.html`
- Test: `tests/test_password_reset.py`

**Steps:**
1. Add GET/POST `/forgot-password`.
2. Always return generic response.
3. Create reset token when user exists.
4. Send reset email.
5. Add GET/POST `/reset-password`.
6. On successful reset, revoke all sessions.

**Verification:**

```bash
python -m pytest tests/test_password_reset.py -q
```

Expected: reset works once, expires correctly, and revokes sessions.

### Task 3.4: Add account/security page

**Files:**
- Create: `src/groot_ops/templates/account_security.html`
- Modify: `src/groot_ops/ui_app.py`
- Test: `tests/test_account_security.py`

**Steps:**
1. Add `/account/security`.
2. Show current account status.
3. Implement change password with current-password confirmation.
4. Add logout-all-devices action.

**Verification:**

```bash
python -m pytest tests/test_account_security.py -q
```

Expected: password change requires current password and revokes other sessions.

---

## Phase 4 — Dashboard persistence and ownership

**Objective:** Save setup and dashboard state in Neon, tied to the authenticated user.

### Task 4.1: Add client repository

**Files:**
- Create: `src/groot_ops/client_repository.py`
- Test: `tests/test_client_repository.py`

**Steps:**
1. Create client for user.
2. Load clients by owner.
3. Load client by slug + owner.
4. Save/update client profile.
5. Save/update client config.

**Verification:**

```bash
python -m pytest tests/test_client_repository.py -q
```

Expected: users can only load their own clients.

### Task 4.2: Modify setup save to DB

**Files:**
- Modify: `src/groot_ops/ui_config_service.py`
- Modify: `src/groot_ops/ui_app.py`
- Test: `tests/test_ui_config_service.py`, `tests/test_setup_db_persistence.py`

**Steps:**
1. Keep YAML path for local/dev if explicitly configured.
2. In production/auth mode, save setup to Neon.
3. Generate stable client slug.
4. Validate Google Sheet URL/ID.
5. Redirect to dashboard after save.

**Verification:**

```bash
python -m pytest tests/test_ui_config_service.py tests/test_setup_db_persistence.py -q
```

Expected: setup persists to DB and reloads after new request.

### Task 4.3: Load dashboard from DB

**Files:**
- Modify: `src/groot_ops/ui_app.py`
- Modify: `src/groot_ops/templates/dashboard.html`
- Test: `tests/test_dashboard_db_loading.py`

**Steps:**
1. `/dashboard` loads the current user’s default client.
2. If none exists, redirect to `/setup`.
3. `/clients/<slug>/dashboard` checks ownership.
4. Show saved business/config values.

**Verification:**

```bash
python -m pytest tests/test_dashboard_db_loading.py -q
```

Expected: dashboard access is user-owned and persistent.

### Task 4.4: Integrate DB config with existing lead preview/summary preview

**Files:**
- Modify: `src/groot_ops/repository_factory.py` or adapter layer as needed
- Modify: `src/groot_ops/ui_app.py`
- Test: `tests/test_dashboard_preview_from_db_config.py`

**Steps:**
1. Convert DB config into existing `ClientConfig` model.
2. Reuse existing Google Sheets/CSV repository logic.
3. Keep existing lead scoring/drafting behavior unchanged.

**Verification:**

```bash
python -m pytest tests/test_dashboard_preview_from_db_config.py -q
```

Expected: dashboard preview works from DB-backed config.

---

## Phase 5 — Admin/operator controls

**Objective:** Give Rex/Groot/Drax lightweight visibility and support tools for pilot users.

### Task 5.1: Add admin role checks

**Files:**
- Modify: auth middleware/helper files
- Test: `tests/test_admin_auth.py`

**Steps:**
1. Add role field support: `user`, `admin`.
2. Add admin guard helper.
3. Block non-admin users from `/admin`.

**Verification:**

```bash
python -m pytest tests/test_admin_auth.py -q
```

Expected: admins pass; normal users receive 403/redirect.

### Task 5.2: Add admin users/clients page

**Files:**
- Modify: `src/groot_ops/ui_app.py`
- Create: `src/groot_ops/templates/admin.html`
- Create: `src/groot_ops/templates/admin_users.html`
- Create: `src/groot_ops/templates/admin_clients.html`
- Test: `tests/test_admin_pages.py`

**Steps:**
1. List users.
2. List clients.
3. Show setup status.
4. Show last login/last run summary where available.
5. Do not expose password hashes or tokens.

**Verification:**

```bash
python -m pytest tests/test_admin_pages.py -q
```

Expected: admin pages render safe data only.

### Task 5.3: Add admin account support actions

**Files:**
- Modify: admin routes/templates
- Test: `tests/test_admin_support_actions.py`

**Steps:**
1. Disable/enable user.
2. Revoke user sessions.
3. Trigger password reset email.
4. Log audit events.

**Verification:**

```bash
python -m pytest tests/test_admin_support_actions.py -q
```

Expected: support actions work and are audited.

---

## Phase 6 — Production hardening and observability

**Objective:** Make the stable PoC safe enough for real early testers.

### Task 6.1: Add CSRF protection

**Files:**
- Create/Modify: `src/groot_ops/security/csrf.py`
- Modify: form templates
- Test: `tests/test_csrf.py`

**Steps:**
1. Generate per-session CSRF token.
2. Add hidden field to state-changing forms.
3. Reject missing/invalid tokens.
4. Ensure logout/setup/password routes are protected.

**Verification:**

```bash
python -m pytest tests/test_csrf.py -q
```

Expected: invalid CSRF rejected; valid forms pass.

### Task 6.2: Add DB-backed rate limiting for auth routes

**Files:**
- Create: `src/groot_ops/auth/rate_limit.py`
- Test: `tests/test_auth_rate_limit.py`

**Steps:**
1. Track attempts by normalized email and hashed IP.
2. Limit failed login attempts.
3. Limit password reset requests.
4. Keep user-facing messages generic.

**Verification:**

```bash
python -m pytest tests/test_auth_rate_limit.py -q
```

Expected: excessive attempts are blocked safely.

### Task 6.3: Add security headers

**Files:**
- Modify: `src/groot_ops/ui_app.py` or middleware file
- Test: `tests/test_security_headers.py`

**Headers:**
- `Strict-Transport-Security`
- `X-Content-Type-Options`
- `X-Frame-Options`
- `Referrer-Policy`
- `Content-Security-Policy`

**Verification:**

```bash
python -m pytest tests/test_security_headers.py -q
```

Expected: required headers are present.

### Task 6.4: Add retention cleanup command

**Files:**
- Create: `src/groot_ops/main_cleanup.py`
- Test: `tests/test_cleanup.py`

**Steps:**
1. Delete expired sessions.
2. Delete used/expired reset and verification tokens.
3. Optionally prune old login attempts.
4. Keep audit events lightweight.

**Verification:**

```bash
python -m pytest tests/test_cleanup.py -q
```

Expected: cleanup removes expired transient auth data only.

---

## Phase 7 — Pilot QA and Vercel deployment

**Objective:** Deploy stable PoC and verify real user flow end-to-end.

### Task 7.1: Configure Neon environment

**Files:**
- Vercel environment variables, no code committed.
- Local `.env`, no secret printing.

**Required env vars:**
- `DATABASE_URL`
- existing Maton/Gmail env as needed
- app secret/session signing secret if implemented

**Verification:**

```bash
python scripts/production_readiness_check.py
```

Expected: readiness passes without exposing secrets.

### Task 7.2: Run full test suite

**Command:**

```bash
python -m pytest -q
python scripts/production_readiness_check.py
```

Expected: all tests pass; readiness passes.

### Task 7.3: Deploy to Vercel production

**Command:**

```bash
cd /opt/data/groot-ops
set -a
. ./.env
set +a
npx vercel --prod --yes --token "$VERCEL_TOKEN"
```

**Verification:**

```bash
curl -sS https://groot-ops.vercel.app/health
curl -sS https://groot-ops.vercel.app/ready
```

Expected: health OK; ready reports DB/config ready safely.

### Task 7.4: Manual QA checklist

**Checklist:**

1. Open `https://groot-ops.vercel.app`.
2. Click Start Setup.
3. Confirm signup page appears, not token wall.
4. Create test account.
5. Log out.
6. Log in.
7. Request password reset.
8. Reset password.
9. Verify email.
10. Create business setup.
11. Save Google Sheet config.
12. Refresh browser; setup persists.
13. Open dashboard; dashboard shows saved config.
14. Try accessing another user/client dashboard; access denied.
15. Open admin as admin user; users/clients visible.
16. Confirm no customer-facing auto-send exists.

**Expected:** Full early-user flow works on the stable Vercel domain.

## Definition of done for Stable PoC

The rollout is done when:

- users can sign up, log in, log out, reset password, and verify email;
- setup saves to Neon and persists after redeploy;
- dashboard access is session-based and user-owned;
- token wall no longer blocks normal users;
- admin/operator can view pilot users/clients;
- Google Sheet validation and previews still work;
- no customer-facing messages are auto-sent;
- tests and production readiness checks pass;
- `https://groot-ops.vercel.app/health` and `/ready` are healthy.
