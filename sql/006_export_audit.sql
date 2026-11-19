-- Apply once after a verified local database backup. No existing table is dropped.
CREATE TABLE IF NOT EXISTS public.export_audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES public.app_users(id) ON DELETE RESTRICT,
    dataset text NOT NULL CHECK (dataset IN ('questions','tests','high_yield_topics')),
    format text NOT NULL CHECK (format IN ('csv','xlsx','json')),
    row_count integer NOT NULL CHECK (row_count >= 0),
    filter_by text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_export_audit_created_at ON public.export_audit_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exam_sessions_user_completed ON public.exam_sessions (user_id, is_completed, end_time DESC);
CREATE INDEX IF NOT EXISTS idx_questions_subject_year ON public.questions (subject_id, year);
