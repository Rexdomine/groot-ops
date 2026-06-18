# Groot Ops Stable PoC System Design

Last updated: 2026-06-18
Owner: Rex / Princewill Ejiogu
Project: Groot Ops
Repository: `/opt/data/groot-ops`
Production URL for PoC: `https://groot-ops.vercel.app`

## Decision status

This document is the locked system-design baseline for the Groot Ops Stable PoC rollout.

When resuming Groot Ops, read this file and `PROJECT_HANDOFF_CHECKPOINT.md` before implementing or changing direction.

## Product goal

Groot Ops should become a stable, no-cost proof-of-concept that early users can actually sign up for, log into, configure, and return to without relying on private tokenized links or temporary demo storage.

The PoC should prove that Groot Ops can help small businesses, starting with real estate operators, manage lead follow-up more intelligently while staying safe and human-reviewed.

## Locked PoC architecture

```text
User
  ↓
https://groot-ops.vercel.app
  ↓
Vercel-hosted FastAPI/Jinja app
  ↓
Custom authentication layer
  - signup
  - login
  - logout
  - account/session management
  - password reset
  - email verification
  ↓
Neon Postgres free database
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
Maton/Gmail for low-volume app emails
  - verification emails
  - password reset emails
  - setup confirmations
  - owner summaries
```

## Platform decisions

### Hosting

Use Vercel free hosting for the PoC.

Canonical PoC URL:

- `https://groot-ops.vercel.app`

A custom domain is not required for the PoC because cost must remain zero for now. The Vercel-provided production domain is sufficient for early testers.

### Backend hosting

Keep the current FastAPI app on Vercel for now.

Do not move to Render free for the PoC. Render free web services spin down after idle time, and Render free Postgres expires after 30 days. That creates reliability/data-retention risk for early users.

### Database

Use Neon Postgres free.

Rex-provided free-plan basis:

- `$0`
- no time limit
- no credit card required
- 100 projects
- 100 CU-hours monthly per project
- 0.5 GB storage per project
- sizes up to 2 CU / 8 GB RAM
- Neon Auth: 60K MAUs available, but not used for this PoC auth design
- 6-hour time travel/restores
- autoscaling, branching, read replicas
- unlimited team members

### Authentication

Build custom app-owned authentication. Do not use third-party hosted auth as the primary PoC auth layer.

Use secure server-side sessions, not pure stateless JWT, for the browser dashboard.

Recommended auth model:

```text
Secure HttpOnly cookie
+ random opaque session token
+ hashed session token stored in Neon
```

JWT can be added later for external APIs, mobile clients, or integrations, but should not be the primary browser session mechanism during the PoC.

### Email

Use Maton/Gmail for low-volume PoC emails:

- email verification
- password reset
- setup confirmation
- owner summaries

Later, after revenue or higher usage, move transactional email to Resend, Postmark, SendGrid, or AWS SES.

### Lead source

Keep user Google Sheets as the source of truth for lead records.

Neon should store app/account/config metadata, not full CRM lead history.

## Neon storage discipline

Because Neon free provides 0.5 GB storage per project, Groot Ops must avoid storing heavy data in Neon.

### Store in Neon

- users
- sessions
- email verification tokens
- password reset tokens
- login/rate-limit attempts
- business/client profiles
- client automation configs
- Google Sheet IDs/URLs and sheet names
- setup status
- automation run summaries
- lightweight audit events

### Keep in Google Sheets

- actual lead rows
- lead scores
- draft messages
- approval status fields
- detailed activity log rows

### Do not store in Neon during PoC

- full raw lead history for every user
- uploaded files
- large email bodies
- attachments/images
- huge debug logs
- full AI-generation history

## User-facing experience target

Current problem:

```text
Click Start Setup or View Dashboard
→ Dashboard access required
→ private token link needed
```

Target PoC experience:

```text
Open https://groot-ops.vercel.app
→ Click Start Setup
→ Sign up or log in
→ Create business profile
→ Connect Google Sheet
→ Save setup to Neon
→ View dashboard
→ Return later and log in again
```

## Auth requirements

### Signup

Users can create an account with:

- full name
- email
- password
- confirm password

System behavior:

- normalize email
- enforce password rules
- hash password with Argon2id, bcrypt fallback only if Argon2 is problematic
- create user record
- send email verification token
- create session or allow immediate dashboard with verification banner
- require email verification before automation activation

### Login

Users can log in with email/password.

Security behavior:

- generic failure message: `Invalid email or password.`
- no user enumeration through error messages
- rate-limit failed attempts
- create server-side session
- set secure cookie
- redirect to setup or dashboard

### Logout

Users can log out current session.

System should delete/revoke the session row and clear the cookie.

### Session management

Support:

- current session tracking
- optional list of active sessions
- logout all devices
- revoke suspicious sessions
- session expiry

Recommended session settings:

- idle timeout: 7 days
- absolute lifetime: 30 days
- cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`

### Password recovery

Routes:

- `/forgot-password`
- `/reset-password?token=...`

Flow:

1. user requests reset by email
2. app always responds generically: `If that email exists, reset instructions will be sent.`
3. generate random token
4. store only hashed token in Neon
5. token expires after 15–30 minutes
6. reset password invalidates all existing sessions

### Email verification

Routes:

- `/verify-email?token=...`
- `/resend-verification`

Email verification should be required before enabling automation/owner email workflows for a client.

### Change password

Requires active session and current password confirmation.

After password change:

- update password hash
- revoke other sessions
- audit event created

## Security baseline

Follow OWASP-style authentication practices:

- passwords transmitted only over HTTPS
- password hashes stored with Argon2id or bcrypt fallback
- generic auth responses to avoid user enumeration
- DB-backed rate limiting for auth routes
- CSRF protection for state-changing forms
- secure cookies
- audit logging for auth/security events
- no plaintext passwords ever
- no secrets printed, committed, or stored in docs

Security headers to add/verify:

- `Strict-Transport-Security`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: same-origin`
- `Content-Security-Policy`

## Required database tables

- `users`
- `sessions`
- `email_verification_tokens`
- `password_reset_tokens`
- `login_attempts`
- `clients`
- `client_configs`
- `automation_runs`
- `audit_events`

## Dashboard behavior

Public routes:

- `/`
- `/signup`
- `/login`
- `/forgot-password`
- `/reset-password`
- `/verify-email`

Authenticated user routes:

- `/setup`
- `/dashboard`
- `/clients/<client_slug>/dashboard`
- `/account`
- `/account/security`

Admin/operator routes:

- `/admin`
- `/admin/users`
- `/admin/clients`
- `/admin/runs`

Admin routes require logged-in user with `role='admin'`.

## Automation safety boundary

During Stable PoC, Groot Ops must not auto-send customer-facing messages.

Allowed:

- Google Sheet validation
- lead scoring
- follow-up draft generation
- approval queue
- owner dashboard
- owner daily summary
- setup confirmation emails
- password/account emails

Not allowed yet:

- automatic emails to leads
- automatic SMS to leads
- automatic WhatsApp messages
- automatic social DMs

Future customer-facing sends require a separate explicit design/review phase with approval gating, duplicate-send protection, client channel opt-in, and audit logs.

## Acceptance criteria for Stable PoC

Before inviting real testers:

- user opens `https://groot-ops.vercel.app`
- user clicks Start Setup
- user can sign up
- user can log in
- user can log out
- user can request password reset
- user can verify email
- user can save business setup
- setup persists after refresh/redeploy
- user can return later and see dashboard
- user only sees their own client dashboard
- admin can view pilot users/clients
- Google Sheet validation still works
- daily summary preview still works
- lead draft preview still works
- `/health` returns OK
- `/ready` confirms DB connectivity and required app configuration
- no customer-facing auto-send is enabled

## Upgrade path after revenue

When usage/revenue justifies paid infrastructure:

- custom domain
- paid Neon/Vercel or alternate Postgres
- dedicated transactional email provider
- background workers
- deeper monitoring/alerts
- billing/subscription module
- optional migration to AWS/Render paid/Railway/Fly.io if needed
- customer-facing sends only after explicit safe-send phase
