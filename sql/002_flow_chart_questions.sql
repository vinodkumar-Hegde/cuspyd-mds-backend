-- Only required if flow_chart_questions does not already exist.
-- Existing data is untouched. File values are supplied by the authenticated admin API.
CREATE TABLE IF NOT EXISTS public.flow_chart_questions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id text,
  question_text text NOT NULL,
  correct_answer text NOT NULL,
  explanation text NOT NULL,
  generated_flowchart jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
