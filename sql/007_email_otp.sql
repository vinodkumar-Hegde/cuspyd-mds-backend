-- MDSLate v4 email verification; PostgreSQL 16.
-- Additive and idempotent. No existing account or exam/question rows deleted.
ALTER TABLE public.app_users ADD COLUMN IF NOT EXISTS token_version integer NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS public.auth_pending_registrations (
    email text PRIMARY KEY,
    password_hash text NOT NULL,
    name text NOT NULL,
    mobile text,
    college text,
    state text,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.auth_email_challenges (
    email text NOT NULL,
    purpose text NOT NULL CHECK (purpose IN ('register', 'reset')),
    code_digest text NOT NULL,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    expires_at timestamptz NOT NULL,
    issued_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (email, purpose)
);

CREATE TABLE IF NOT EXISTS public.auth_otp_rate_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email_digest text NOT NULL,
    ip_digest text NOT NULL,
    action text NOT NULL CHECK (action IN ('request','confirm','login')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_auth_otp_events_email ON public.auth_otp_rate_events (email_digest, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_otp_events_ip ON public.auth_otp_rate_events (ip_digest, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auth_pending_expires ON public.auth_pending_registrations (expires_at);

-- Use a dedicated app user with least-privilege permissions in production.
