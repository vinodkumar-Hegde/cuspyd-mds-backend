-- Apply with psql as the schema owner AFTER migrations.
-- Required psql variable: -v runtime_role=YOUR_EXISTING_RUNTIME_ROLE
-- Does not create roles, passwords, extensions or tables.
\set ON_ERROR_STOP on
BEGIN;
GRANT USAGE ON SCHEMA public TO :"runtime_role";
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.app_users, public.profiles, public.questions, public.tests,
    public.exam_sessions, public.feature_settings, public.high_yield_topics,
    public.subject_backgrounds, public.syndromes, public.flow_chart_questions,
    public.subjects, public.app_settings, public.auth_pending_registrations,
    public.auth_email_challenges, public.auth_otp_rate_events
    TO :"runtime_role";
GRANT SELECT ON TABLE public.schema_migrations TO :"runtime_role";
GRANT SELECT, INSERT ON TABLE public.export_audit_events TO :"runtime_role";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"runtime_role";
COMMIT;
