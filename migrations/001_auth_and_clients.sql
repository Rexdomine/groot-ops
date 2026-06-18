CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS schema_migrations (
    name text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL,
    email_normalized text NOT NULL,
    password_hash text NOT NULL,
    full_name text NOT NULL,
    role text NOT NULL DEFAULT 'user',
    status text NOT NULL DEFAULT 'active',
    email_verified_at timestamptz,
    last_login_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (email_normalized),
    CONSTRAINT users_role_check CHECK (role IN ('user', 'admin')),
    CONSTRAINT users_status_check CHECK (status IN ('active', 'disabled', 'pending_verification'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token_hash text NOT NULL UNIQUE,
    user_agent text,
    ip_hash text,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_active_token_hash ON sessions(session_token_hash) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS email_verification_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_email_verification_tokens_user_id ON email_verification_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_email_verification_tokens_expires_at ON email_verification_tokens(expires_at);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    requested_ip_hash text,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id ON password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires_at ON password_reset_tokens(expires_at);

CREATE TABLE IF NOT EXISTS login_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email_normalized text,
    ip_hash text,
    success boolean NOT NULL DEFAULT false,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_email_created ON login_attempts(email_normalized, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_created ON login_attempts(ip_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS clients (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_slug text NOT NULL,
    business_name text NOT NULL,
    agent_name text NOT NULL,
    agent_email text NOT NULL,
    agent_phone text,
    timezone text NOT NULL DEFAULT 'UTC',
    setup_status text NOT NULL DEFAULT 'draft',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner_user_id, client_slug),
    CONSTRAINT clients_setup_status_check CHECK (setup_status IN ('draft', 'configured', 'active', 'paused'))
);

CREATE INDEX IF NOT EXISTS idx_clients_owner_user_id ON clients(owner_user_id);

CREATE TABLE IF NOT EXISTS client_configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL UNIQUE REFERENCES clients(id) ON DELETE CASCADE,
    spreadsheet_id text,
    spreadsheet_url text,
    leads_sheet_name text NOT NULL DEFAULT 'Leads',
    activity_log_sheet_name text NOT NULL DEFAULT 'Activity Log',
    column_mapping jsonb NOT NULL DEFAULT '{}'::jsonb,
    owner_notification_enabled boolean NOT NULL DEFAULT true,
    owner_notification_channel text NOT NULL DEFAULT 'telegram',
    owner_notification_destination text,
    daily_summary_time text NOT NULL DEFAULT '08:30',
    process_leads_frequency text NOT NULL DEFAULT 'every_2h_weekdays',
    automation_status text NOT NULL DEFAULT 'demo_manual',
    required_disclaimer text NOT NULL DEFAULT 'Reply STOP to opt out.',
    max_draft_chars integer NOT NULL DEFAULT 700,
    scoring_settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    voice text NOT NULL DEFAULT 'friendly, concise, professional',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT client_configs_channel_check CHECK (owner_notification_channel IN ('email', 'telegram', 'none')),
    CONSTRAINT client_configs_automation_status_check CHECK (automation_status IN ('demo_manual', 'draft', 'active', 'paused'))
);

CREATE TABLE IF NOT EXISTS automation_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    run_type text NOT NULL,
    status text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_message text,
    CONSTRAINT automation_runs_status_check CHECK (status IN ('running', 'succeeded', 'failed', 'skipped'))
);

CREATE INDEX IF NOT EXISTS idx_automation_runs_client_started ON automation_runs(client_id, started_at DESC);

CREATE TABLE IF NOT EXISTS audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    client_id uuid REFERENCES clients(id) ON DELETE SET NULL,
    event_type text NOT NULL,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    ip_hash text,
    user_agent text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_user_created ON audit_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_client_created ON audit_events(client_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_event_type ON audit_events(event_type);
