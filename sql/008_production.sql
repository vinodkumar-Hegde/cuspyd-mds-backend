-- Explicit, transactional migration; never run DDL in API request handlers.
ALTER TABLE public.app_users ADD COLUMN IF NOT EXISTS legacy_role text;
ALTER TABLE public.app_users ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;
ALTER TABLE public.app_users ADD COLUMN IF NOT EXISTS password_reset_required boolean NOT NULL DEFAULT false;
ALTER TABLE public.app_users ADD COLUMN IF NOT EXISTS mobile_e164 text;
CREATE UNIQUE INDEX IF NOT EXISTS uq_app_users_email_normalized ON public.app_users (lower(btrim(email)));
CREATE UNIQUE INDEX IF NOT EXISTS uq_app_users_mobile_e164 ON public.app_users (mobile_e164);
ALTER TABLE public.tests ADD COLUMN IF NOT EXISTS publish_date timestamptz;
ALTER TABLE public.tests ADD COLUMN IF NOT EXISTS subject_id text;
ALTER TABLE public.tests ADD COLUMN IF NOT EXISTS weightage jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.exam_sessions ADD COLUMN IF NOT EXISTS request_id uuid;
ALTER TABLE public.exam_sessions ADD COLUMN IF NOT EXISTS result_snapshot jsonb;
CREATE UNIQUE INDEX IF NOT EXISTS uq_exam_submission ON public.exam_sessions (user_id, request_id);
CREATE INDEX IF NOT EXISTS idx_tests_available ON public.tests (status, publish_date, created_at);
CREATE TABLE IF NOT EXISTS public.subjects (
    id text PRIMARY KEY, name text NOT NULL, part text NOT NULL CHECK (part IN ('A','B')),
    weightage integer NOT NULL CHECK (weightage >= 0), bds_year text NOT NULL
);
CREATE TABLE IF NOT EXISTS public.app_settings (
    key text PRIMARY KEY, value jsonb NOT NULL
);

-- Initial editable subject catalog, carried over from the existing application.
INSERT INTO public.subjects (id,name,part,weightage,bds_year) VALUES
('anatomy','General Anatomy','A','14','BDS-I'),
('physiology_biochem','General Human Physiology and Biochemistry','A','14','BDS-I'),
('dental_anatomy','Dental Anatomy, Embryology & Oral Histology','A','14','BDS-I'),
('pathology_micro','General Pathology and Microbiology','A','14','BDS-II'),
('pharmacology','General and Dental Pharmacology and Therapeutics','A','14','BDS-II'),
('medicine','General Medicine','A','15','BDS-III'),
('surgery','General Surgery','A','15','BDS-III'),
('materials','Dental Materials','A','14','BDS-II'),
('oral_path','Oral Pathology and Oral Microbiology','A','14','BDS-II'),
('oral_med_rad','Oral Medicine and Radiology','B','14','BDS-III'),
('pedodontics','Pedodontics and Preventive Dentistry','B','14','BDS-IV'),
('orthodontics','Orthodontics & Dentofacial Orthopedics','B','14','BDS-IV'),
('periodontology','Periodontology','B','14','BDS-III'),
('prosthodontics','Prosthodontics and Crown & Bridge','B','14','BDS-IV'),
('conservative_endo','Conservative Dentistry and Endodontics','B','14','BDS-IV'),
('oral_surgery','Oral and Maxillofacial Surgery','B','14','BDS-IV'),
('public_health','Public Health Dentistry','B','14','BDS-IV')
ON CONFLICT DO NOTHING;
