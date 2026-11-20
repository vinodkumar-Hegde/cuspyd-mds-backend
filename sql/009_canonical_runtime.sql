-- Explicit publishing, canonical account policy and immutable attempt reads.
-- Data conversion and retirement run once in migrations/canonical.py in this transaction.
ALTER TABLE public.questions ADD COLUMN image_practice_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE public.app_users ADD COLUMN email_recovery_allowed boolean NOT NULL DEFAULT true;
UPDATE public.app_users SET email_recovery_allowed=false
WHERE role='admin' OR lower(legacy_role)='admin';
UPDATE public.tests SET status='PUBLISHED' WHERE status='ACTIVE';
UPDATE public.tests SET status='DRAFT' WHERE status IS NULL;
ALTER TABLE public.tests ALTER COLUMN status SET NOT NULL;
ALTER TABLE public.tests ADD CONSTRAINT tests_status_check
    CHECK (status IN ('DRAFT','LOCKED','PUBLISHED','SCHEDULED','ARCHIVED'));
CREATE INDEX idx_tests_question_ids ON public.tests USING gin (questions);
CREATE INDEX idx_questions_image_practice ON public.questions (id)
    WHERE image_practice_enabled AND image_url IS NOT NULL;
CREATE INDEX idx_exam_sessions_history ON public.exam_sessions (user_id,start_time DESC,id);
CREATE SCHEMA IF NOT EXISTS retired;
REVOKE ALL ON SCHEMA retired FROM PUBLIC;
COMMENT ON SCHEMA retired IS 'Preserved historical data; no application runtime access or dependency.';
