# Database dictionary

This reference is generated from PostgreSQL 16 catalog metadata after the current migrations ran against a fresh disposable database. No application rows, credentials or contact data are exported. It describes the fresh-install schema, not every object retained in an upgraded legacy database.

The authority is `sql/*.sql` executed by `python -m app.migrate`. Do not use this document as an alternative migration script. The six files run in filename order: `000_core.sql`, `001_auth.sql`, `002_flow_chart_questions.sql`, `006_export_audit.sql`, `007_email_otp.sql`, `008_production.sql`. Gaps in numbering and overlapping `CREATE TABLE IF NOT EXISTS` statements are intentional migration history. The runner creates `schema_migrations` itself.

## Table inventory and definitions

| Table | Columns | Purpose |
| --- | --- | --- |
| `app_settings` | 2 | Generic JSON settings store; currently unused by API operations. |
| `app_users` | 14 | Canonical identity, Argon2 password hash, role and token revocation state. |
| `auth_email_challenges` | 6 | One HMAC OTP challenge per normalized email and purpose. |
| `auth_otp_rate_events` | 5 | Keyed email/IP digests and actions for shared rate limiting. |
| `auth_pending_registrations` | 8 | Unverified registration payload, hash and expiry. |
| `exam_sessions` | 11 | Owned attempts, scoring, retry identity and new-submission snapshots. |
| `export_audit_events` | 7 | Administrator export actor, dataset, format, row count and filter. |
| `feature_settings` | 2 | Student feature visibility enforced by the API. |
| `flow_chart_questions` | 7 | Question, answer, explanation and generated flowchart JSON. |
| `high_yield_topics` | 7 | Subject/year learning topics with question and answer images. |
| `profiles` | 8 | Compatibility profile mirror; app_users is the authentication authority. |
| `questions` | 9 | Question bank: four options, zero-based answer key, optional image. |
| `schema_migrations` | 2 | Applied SQL filenames/timestamps, managed by the migration job. |
| `subject_backgrounds` | 4 | Unique subject-name to image mapping. |
| `subjects` | 5 | Editable subject catalog, BDS year, part and weightage; 17 seeded rows. |
| `syndromes` | 5 | Syndrome cards and images. |
| `tests` | 12 | Test metadata, publication state and ordered JSON question identifiers. |

**Total: 17 tables, 114 columns.**

`Nullable` describes the database definition, not the API input contract. A dash means no default. Constraint-backed indexes are not repeated as additional indexes.

### `app_settings`

Generic JSON settings store; currently unused by API operations.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `key` | `text` | No | `-` |
| `value` | `jsonb` | No | `-` |

Constraints:

- `app_settings_pkey`: `PRIMARY KEY (key)`

### `app_users`

Canonical identity, Argon2 password hash, role and token revocation state.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `gen_random_uuid()` |
| `email` | `text` | Yes | `-` |
| `password_hash` | `text` | Yes | `-` |
| `name` | `text` | No | `-` |
| `mobile` | `text` | Yes | `-` |
| `college` | `text` | Yes | `-` |
| `state` | `text` | Yes | `-` |
| `role` | `text` | No | `'student'::text` |
| `legacy_role` | `text` | Yes | `-` |
| `is_active` | `boolean` | No | `true` |
| `password_reset_required` | `boolean` | No | `false` |
| `token_version` | `integer` | No | `0` |
| `created_at` | `timestamp with time zone` | No | `now()` |
| `mobile_e164` | `text` | Yes | `-` |

Constraints:

- `app_users_email_key`: `UNIQUE (email)`
- `app_users_pkey`: `PRIMARY KEY (id)`
- `app_users_role_check`: `CHECK ((role = ANY (ARRAY['student'::text, 'admin'::text])))`

Additional indexes:

```sql
CREATE INDEX idx_app_users_role ON public.app_users USING btree (role);
CREATE UNIQUE INDEX uq_app_users_email_normalized ON public.app_users USING btree (lower(btrim(email)));
CREATE UNIQUE INDEX uq_app_users_mobile_e164 ON public.app_users USING btree (mobile_e164);
```

### `auth_email_challenges`

One HMAC OTP challenge per normalized email and purpose.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `email` | `text` | No | `-` |
| `purpose` | `text` | No | `-` |
| `code_digest` | `text` | No | `-` |
| `attempts` | `integer` | No | `0` |
| `expires_at` | `timestamp with time zone` | No | `-` |
| `issued_at` | `timestamp with time zone` | No | `now()` |

Constraints:

- `auth_email_challenges_attempts_check`: `CHECK ((attempts >= 0))`
- `auth_email_challenges_pkey`: `PRIMARY KEY (email, purpose)`
- `auth_email_challenges_purpose_check`: `CHECK ((purpose = ANY (ARRAY['register'::text, 'reset'::text])))`

### `auth_otp_rate_events`

Keyed email/IP digests and actions for shared rate limiting.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `bigint` | No | `GENERATED ALWAYS AS IDENTITY` |
| `email_digest` | `text` | No | `-` |
| `ip_digest` | `text` | No | `-` |
| `action` | `text` | No | `-` |
| `created_at` | `timestamp with time zone` | No | `now()` |

Constraints:

- `auth_otp_rate_events_action_check`: `CHECK ((action = ANY (ARRAY['request'::text, 'confirm'::text, 'login'::text])))`
- `auth_otp_rate_events_pkey`: `PRIMARY KEY (id)`

Additional indexes:

```sql
CREATE INDEX idx_auth_otp_events_email ON public.auth_otp_rate_events USING btree (email_digest, created_at DESC);
CREATE INDEX idx_auth_otp_events_ip ON public.auth_otp_rate_events USING btree (ip_digest, created_at DESC);
```

### `auth_pending_registrations`

Unverified registration payload, hash and expiry.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `email` | `text` | No | `-` |
| `password_hash` | `text` | No | `-` |
| `name` | `text` | No | `-` |
| `mobile` | `text` | Yes | `-` |
| `college` | `text` | Yes | `-` |
| `state` | `text` | Yes | `-` |
| `expires_at` | `timestamp with time zone` | No | `-` |
| `created_at` | `timestamp with time zone` | No | `now()` |

Constraints:

- `auth_pending_registrations_pkey`: `PRIMARY KEY (email)`

Additional indexes:

```sql
CREATE INDEX idx_auth_pending_expires ON public.auth_pending_registrations USING btree (expires_at);
```

### `exam_sessions`

Owned attempts, scoring, retry identity and new-submission snapshots.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `gen_random_uuid()` |
| `user_id` | `uuid` | Yes | `-` |
| `test_id` | `uuid` | Yes | `-` |
| `type` | `text` | No | `-` |
| `start_time` | `timestamp with time zone` | Yes | `now()` |
| `end_time` | `timestamp with time zone` | Yes | `-` |
| `answers` | `jsonb` | Yes | `-` |
| `marked_for_review` | `uuid[]` | Yes | `-` |
| `is_completed` | `boolean` | Yes | `false` |
| `request_id` | `uuid` | Yes | `-` |
| `result_snapshot` | `jsonb` | Yes | `-` |

Constraints:

- `exam_sessions_pkey`: `PRIMARY KEY (id)`
- `exam_sessions_test_id_fkey`: `FOREIGN KEY (test_id) REFERENCES tests(id)`
- `exam_sessions_user_id_fkey`: `FOREIGN KEY (user_id) REFERENCES app_users(id)`

Additional indexes:

```sql
CREATE INDEX idx_exam_sessions_user_completed ON public.exam_sessions USING btree (user_id, is_completed, end_time DESC);
CREATE UNIQUE INDEX uq_exam_submission ON public.exam_sessions USING btree (user_id, request_id);
```

### `export_audit_events`

Administrator export actor, dataset, format, row count and filter.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `bigint` | No | `GENERATED ALWAYS AS IDENTITY` |
| `actor_id` | `uuid` | No | `-` |
| `dataset` | `text` | No | `-` |
| `format` | `text` | No | `-` |
| `row_count` | `integer` | No | `-` |
| `filter_by` | `text` | Yes | `-` |
| `created_at` | `timestamp with time zone` | No | `now()` |

Constraints:

- `export_audit_events_actor_id_fkey`: `FOREIGN KEY (actor_id) REFERENCES app_users(id) ON DELETE RESTRICT`
- `export_audit_events_dataset_check`: `CHECK ((dataset = ANY (ARRAY['questions'::text, 'tests'::text, 'high_yield_topics'::text])))`
- `export_audit_events_format_check`: `CHECK ((format = ANY (ARRAY['csv'::text, 'xlsx'::text, 'json'::text])))`
- `export_audit_events_pkey`: `PRIMARY KEY (id)`
- `export_audit_events_row_count_check`: `CHECK ((row_count >= 0))`

Additional indexes:

```sql
CREATE INDEX idx_export_audit_created_at ON public.export_audit_events USING btree (created_at DESC);
```

### `feature_settings`

Student feature visibility enforced by the API.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `feature_key` | `text` | No | `-` |
| `is_visible` | `boolean` | No | `true` |

Constraints:

- `feature_settings_pkey`: `PRIMARY KEY (feature_key)`

### `flow_chart_questions`

Question, answer, explanation and generated flowchart JSON.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `gen_random_uuid()` |
| `subject_id` | `text` | Yes | `-` |
| `question_text` | `text` | No | `-` |
| `correct_answer` | `text` | No | `-` |
| `explanation` | `text` | No | `-` |
| `generated_flowchart` | `jsonb` | Yes | `-` |
| `created_at` | `timestamp with time zone` | No | `now()` |

Constraints:

- `flow_chart_questions_pkey`: `PRIMARY KEY (id)`

### `high_yield_topics`

Subject/year learning topics with question and answer images.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `gen_random_uuid()` |
| `subject_id` | `text` | No | `-` |
| `year` | `text` | No | `-` |
| `topic_name` | `text` | No | `-` |
| `created_at` | `timestamp with time zone` | Yes | `now()` |
| `question_image_url` | `text` | Yes | `-` |
| `answer_image_url` | `text` | Yes | `-` |

Constraints:

- `high_yield_topics_pkey`: `PRIMARY KEY (id)`

### `profiles`

Compatibility profile mirror; app_users is the authentication authority.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `-` |
| `name` | `text` | Yes | `-` |
| `email` | `text` | Yes | `-` |
| `mobile` | `text` | Yes | `-` |
| `college` | `text` | Yes | `-` |
| `state` | `text` | Yes | `-` |
| `role` | `text` | Yes | `'student'::text` |
| `created_at` | `timestamp with time zone` | Yes | `now()` |

Constraints:

- `profiles_email_key`: `UNIQUE (email)`
- `profiles_id_fkey`: `FOREIGN KEY (id) REFERENCES app_users(id) ON DELETE CASCADE`
- `profiles_pkey`: `PRIMARY KEY (id)`

### `questions`

Question bank: four options, zero-based answer key, optional image.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `gen_random_uuid()` |
| `subject_id` | `text` | No | `-` |
| `year` | `text` | No | `-` |
| `text` | `text` | No | `-` |
| `options` | `text[]` | No | `-` |
| `correct_option` | `integer` | No | `-` |
| `explanation` | `text` | No | `''::text` |
| `topic` | `text` | Yes | `-` |
| `image_url` | `text` | Yes | `-` |

Constraints:

- `questions_correct_option_check`: `CHECK (((correct_option >= 0) AND (correct_option <= 3)))`
- `questions_options_check`: `CHECK ((cardinality(options) = 4))`
- `questions_pkey`: `PRIMARY KEY (id)`

Additional indexes:

```sql
CREATE INDEX idx_questions_subject_year ON public.questions USING btree (subject_id, year);
```

### `schema_migrations`

Applied SQL filenames/timestamps, managed by the migration job.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `version` | `text` | No | `-` |
| `applied_at` | `timestamp with time zone` | No | `now()` |

Constraints:

- `schema_migrations_pkey`: `PRIMARY KEY (version)`

### `subject_backgrounds`

Unique subject-name to image mapping.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `integer` | No | `GENERATED BY DEFAULT AS IDENTITY` |
| `subject_name` | `text` | No | `-` |
| `image_url` | `text` | No | `-` |
| `created_at` | `timestamp with time zone` | Yes | `now()` |

Constraints:

- `subject_backgrounds_pkey`: `PRIMARY KEY (id)`
- `subject_backgrounds_subject_name_key`: `UNIQUE (subject_name)`

### `subjects`

Editable subject catalog, BDS year, part and weightage; 17 seeded rows.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `text` | No | `-` |
| `name` | `text` | No | `-` |
| `part` | `text` | No | `-` |
| `weightage` | `integer` | No | `-` |
| `bds_year` | `text` | No | `-` |

Constraints:

- `subjects_part_check`: `CHECK ((part = ANY (ARRAY['A'::text, 'B'::text])))`
- `subjects_pkey`: `PRIMARY KEY (id)`
- `subjects_weightage_check`: `CHECK ((weightage >= 0))`

### `syndromes`

Syndrome cards and images.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `gen_random_uuid()` |
| `name` | `text` | No | `-` |
| `description` | `text` | Yes | `-` |
| `image_url` | `text` | No | `-` |
| `created_at` | `timestamp with time zone` | No | `now()` |

Constraints:

- `syndromes_pkey`: `PRIMARY KEY (id)`

### `tests`

Test metadata, publication state and ordered JSON question identifiers.

| Column | PostgreSQL type | Nullable | Default / identity |
| --- | --- | --- | --- |
| `id` | `uuid` | No | `gen_random_uuid()` |
| `title` | `text` | No | `-` |
| `type` | `text` | No | `-` |
| `status` | `text` | Yes | `'DRAFT'::text` |
| `questions` | `jsonb` | No | `-` |
| `created_at` | `timestamp with time zone` | Yes | `now()` |
| `answer_key` | `jsonb` | Yes | `-` |
| `explanations` | `jsonb` | Yes | `-` |
| `admin_message` | `text` | Yes | `-` |
| `publish_date` | `timestamp with time zone` | Yes | `-` |
| `subject_id` | `text` | Yes | `-` |
| `weightage` | `jsonb` | No | `'{}'::jsonb` |

Constraints:

- `tests_pkey`: `PRIMARY KEY (id)`
- `tests_type_check`: `CHECK ((type = ANY (ARRAY['ST'::text, 'MT'::text, 'GT'::text, 'RANKER'::text, 'MOCK'::text])))`

Additional indexes:

```sql
CREATE INDEX idx_tests_available ON public.tests USING btree (status, publish_date, created_at);
```


## Relationships

| Stored foreign key | Target | Delete behavior |
| --- | --- | --- |
| `profiles.id` | `app_users.id` | CASCADE |
| `exam_sessions.user_id` | `app_users.id` | NO ACTION |
| `exam_sessions.test_id` | `tests.id` | NO ACTION; null for virtual image practice |
| `export_audit_events.actor_id` | `app_users.id` | RESTRICT |

`questions.subject_id`, `high_yield_topics.subject_id`, `flow_chart_questions.subject_id`, and `tests.subject_id` are logical catalog references, not database foreign keys. `tests.questions` contains question UUID strings in JSON, not a join table with foreign keys. API validation must preserve these relationships; do not assume PostgreSQL enforces them. No recursive business triggers or RLS policies are created by these migrations.

## Application contracts and migration caveats

| Field / area | Contract and limits |
| --- | --- |
| Account email | New inputs are trimmed/lowercased. `uq_app_users_email_normalized` enforces `lower(btrim(email))`; the original email unique constraint also remains. Legacy nulls are permitted by the fresh DDL. |
| Account mobile | Raw `mobile` is preserved for legacy accounts; `mobile_e164` stores the validated canonical unique key. Multiple null keys are allowed. New registration requires a valid mobile and fills both fields. Mobile ownership is not verified by SMS. |
| New passwords | Argon2 hashes only; new/reset input length 12–128. Legacy nullable hashes/activation flags do not permit passwordless accounts through the registration API. |
| Account/profile mirrors | Both tables are written during new registration/admin creation; no synchronization trigger exists. Do not independently edit profile identity fields and assume authentication changes. |
| `tests.questions` | Ordered array of distinct question UUID strings, up to 500 through the API; existence/uniqueness are API checks. |
| `tests.status` | API controls publication/archival values; unlike type, status is not constrained to an enum by the DDL. Scheduling uses `publish_date` and the backend clock. |
| `tests.weightage` | JSON object, default `{}`; application-managed allocation data. |
| `exam_sessions.answers` | New ordinary submissions store score/correct/wrong/unattempted plus an `answers` map of question UUID to option index. Image practice also stores `image_question_id`. Historical payload shapes can differ. |
| `exam_sessions.result_snapshot` | New submissions store `session_id`, public `test` metadata, scoring `results`, and review `questions` including answers/explanations. Restricted to the attempt owner; legacy rows can be null. |
| `exam_sessions.request_id` | Unique with `user_id`; legacy nulls are permitted. Retry-after-archival remains an open review finding. |
| Flowchart/settings JSON | Application-managed JSON, not independently constrained by PostgreSQL JSON Schema. |
| OTP data | Pending registrations contain a password hash/contact details; challenges contain HMAC digests, never plaintext codes. Restrict access and apply bounded retention. |
| Rate-event data | Email/IP fields are keyed digests, not raw addresses; key rotation changes matching. |
| Images | Text URL references, not binary data. Stable API URLs work with local or private S3 storage; see the [integration guide](INTEGRATIONS.md). No schema migration is needed to select S3. |
| Audit retention | Export history is separate from auth cleanup; runtime grants allow insert/select only for the audit table. |

New schema creation does not drop obsolete tables. Previously migrated installations may retain `dashboard_content`, `exam_attempts`, `high_yield_questions`, `user_performance`, `user_profiles` and migration/archive schemas. Inventory those objects and dependencies before retirement. They are not part of a fresh install; this handoff does not delete them.

Migration preflight rejects duplicate normalized identities rather than silently merging accounts. Invalid legacy mobile strings are preserved without canonical keys and need verified correction. Completed sessions without snapshots need a historical-result strategy; today's question bank cannot guarantee reconstruction of old answers. See the [release checklist](RELEASE_CHECKLIST.md).

## Read-only target-environment checks

Run as an authorized operator using your secure PostgreSQL connection. These return metadata/counts, not contact lists.

```sql
SELECT version, applied_at FROM public.schema_migrations ORDER BY version;
SELECT count(*) AS completed_without_snapshot
FROM public.exam_sessions WHERE is_completed AND result_snapshot IS NULL;
SELECT count(*) AS legacy_mobile_without_key
FROM public.app_users
WHERE nullif(btrim(mobile), '') IS NOT NULL AND mobile_e164 IS NULL;
SELECT schemaname, tablename FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schemaname, tablename;
```

Inspect actual constraints/indexes after an upgrade: `IF NOT EXISTS` does not rewrite incompatible legacy definitions. Keep the migration owner separate from the runtime role; [runtime-grants.sql](../deploy/runtime-grants.sql) grants data access without ownership. No default passwords or administrator rows are inserted by the schema.
