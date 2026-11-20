# DevOps handoff

This bundle describes the code shipped in the two repositories. It does not provision AWS resources or certify a production release. Complete the [release checklist](RELEASE_CHECKLIST.md) before public rollout.

## Repositories and ownership

| Repository / owner | Responsibility | Build context |
| --- | --- | --- |
| [Frontend](https://github.com/vinodkumar-Hegde/cuspyd-mds-frontend) / frontend team | React UI, typed HTTP clients, Nginx, browser configuration | Frontend repository root |
| [Backend](https://github.com/vinodkumar-Hegde/cuspyd-mds-backend) / backend team | FastAPI, authorization, OTP, scoring, PostgreSQL migrations, image validation | Backend repository root |
| Backend `deploy/` / DevOps | Image-based deployment, external database connection, runtime role grants, test stack | No sibling checkout required |
| Cloud account / DevOps | TLS, DNS, PostgreSQL service, secrets, SES/SMTP, S3 bucket/IAM, monitoring and recovery | Infrastructure managed separately |

```text
Browser --HTTPS--> ingress --HTTP/private--> frontend Nginx :8080
                                                |
                                          /api/* HTTP
                                                v
                                           FastAPI :8000
                                           |     |     |
                                PostgreSQL/TLS   |     +--> SMTP/TLS or SES
                                                 +--> local volume OR private S3

Alternative: browser --> separately hosted HTTPS API (VITE_API_URL at build time).
S3 reads redirect stable API media URLs to temporary signed HTTPS URLs.
```

The browser never connects to PostgreSQL or sends mail directly. There is no generic SQL/table-query API. The API exposes `/api/auth`, `/api/v1`, `/api/uploads`, and backend question import operations. OpenAPI at `/openapi.json` is the route contract.

## Delivery status

| Area | Current code | Required for deployment |
| --- | --- | --- |
| Independent images | Both Dockerfiles build from their own repo | Publish and record an immutable frontend/backend image pair |
| Database | PostgreSQL 16; six ordered SQL files plus migration runner | Provision owner/runtime roles, CA, credentials, recovery and migration job |
| Schema | 17 tables on a fresh install, including migration bookkeeping | See [dictionary](DATABASE.md); inventory legacy objects separately |
| Email OTP | Implemented SMTP/TLS and SES; HMAC codes, expiry, throttling | Configure sender and secrets; validate real delivery and proxy client IPs |
| Identity uniqueness | Case/space-normalized email and canonical E.164 mobile indexes | Resolve legacy identity conflicts; no fabricated contact replacements |
| Images | Validated files in local storage or a configured private S3 bucket | Supply bucket/region/IAM; copy legacy local assets before removing their volume |
| CI | Separate repo-local checks; backend runs inside Docker | Configure branch protection and your image publishing pipeline |
| Production release | Six review findings remain open | Backend/frontend fixes and deployment acceptance evidence required |

## Backend structure

```text
app/
  main.py                 HTTP app, health/readiness, error boundary
  config.py               Core environment validation
  database.py             PostgreSQL pool, sessions, allowlisted reflection
  security.py             JWT/Argon2, role and feature authorization
  auth.py                 Login, identity, logout
  auth_email.py           Registration/reset OTP and SMTP/SES transport
  identity.py             Email and E.164 mobile normalization
  routes_v1.py            Student content, exams, history, optional AI
  resources.py            Catalog and administrator resource operations
  operations.py           Statistics, exports, export auditing
  uploads.py              Image validation and stable API media routes
  storage.py              Atomic local writes, private S3 writes/signed reads
  import_questions.py     Backend CSV/XLSX import preview
  migrate.py              Locked, finite, transactional migration job
  create_admin.py          Operator-only initial administrator creation
  activate_local_account.py  Verified legacy-account recovery CLI
  maintenance.py          Bounded expired-auth-data cleanup
sql/                      Ordered, immutable migration history
tests/                    Backend helper/integration and container smoke checks
deploy/                   Image deployment, grants and disposable test stack
docs/                     Handoff, schema, integrations, release gates
.github/workflows/ci.yml   Backend repository CI
```

## Runtime environment

The API reads process environment, not an automatic `.env` file. Compose `env_file` injects it. Start from [`.env.example`](../.env.example); supply real values from your secret manager. Do not print resolved Compose configuration with secrets; use `config --quiet`.

| Variable | Requirement / default | Secret | Operational meaning |
| --- | --- | --- | --- |
| `DATABASE_URL` | Required `postgresql+psycopg://...` | Yes | API runtime role; URL-encode credentials; verify DB TLS with the provider CA |
| `JWT_SECRET` | Required, at least 32 random characters | Yes | HS256 signing and keyed limiter identifiers; rotation signs users out and changes limiter digests |
| `OTP_SECRET` | Required for OTP, at least 32 different random characters | Yes | HMAC OTP digests; rotation invalidates outstanding codes |
| `APP_ENV` | `production` for deployment; code default `development` | No | Production rejects the insecure local mail preview |
| `CORS_ORIGIN` | Exact public frontend origin(s), comma-separated | No | Wildcard rejected; include scheme/port and exclude URL paths |
| `PHONE_DEFAULT_REGION` | `IN` | No | Interpretation of national-format mobiles; migration and runtime must agree |
| `ACCESS_TOKEN_MINUTES` | `60`, permitted 5–480 | No | JWT expiry; logout/reset also revoke tokens through database versioning |
| `EXAM_SECONDS_PER_QUESTION` | `60`, permitted 10–600 | No | Exam timing value |
| `UPLOAD_DIR` | Docker `/app/uploads` | No | Local writes in local mode; legacy local reads in either mode |
| `MAX_UPLOAD_BYTES` | `10485760` (10 MiB) | No | Backend upload cap; coordinate any increase with Nginx's 11 MiB request cap |
| `STORAGE_BACKEND` | `local` or `s3`; default `local` | No | Select the implemented storage provider |
| `S3_BUCKET` | Required in S3 mode | No | Private general-purpose bucket |
| `S3_PREFIX` | `uploads`; empty means bucket root | No | Stable environment prefix; changing it requires copying existing objects |
| `S3_REGION` | Falls back to `AWS_REGION`, then `AWS_DEFAULT_REGION` | No | Bucket region; can differ from SES |
| `S3_PRESIGN_SECONDS` | `300`, permitted 60–3600 | No | Lifetime requested for signed reads; role credential expiry can shorten it |
| `S3_KMS_KEY_ID` | Optional | No | Explicit SSE-KMS key; blank uses bucket-default encryption |
| `FORWARDED_ALLOW_IPS` | Uvicorn defaults to loopback trust | No | Set actual trusted proxy IPs/CIDRs; see proxy requirements below |
| `OTP_EMAIL_PROVIDER` | `smtp` or `ses`; default `smtp` | No | Select one of the implemented transports |
| `SMTP_HOST`, `SMTP_FROM` | Required in SMTP mode | No | SMTP endpoint and permitted sender |
| `SMTP_PORT`, `SMTP_SECURITY` | `587`, `starttls`; SSL supported | No | Usually 587/STARTTLS or provider's SSL port; no plaintext production SMTP |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Both set or both empty | Yes | Provider credentials if authentication is required |
| `SES_FROM_EMAIL` | Required in SES mode | No | Verified sender in the configured SES region |
| `AWS_REGION` / `AWS_DEFAULT_REGION` | Required in SES mode | No | Code prefers `AWS_REGION`; SDK obtains credentials through its default chain |
| `GEMINI_API_KEY` | Optional | Yes | Backend-only AI credential; missing key disables AI operations |
| `GEMINI_MODEL` | `gemini-2.5-flash` | No | Existing configured model default; verify provider availability before enabling |

`OTP_LOCAL_PREVIEW` and Mailpit belong to local development, not the deployment bundle. `SES_ENV_FILE` is a parent-workspace local SSO override variable, not an API setting. All `VITE_*` variables are public browser build inputs; none may contain secrets. S3 and SES obtain credentials through the AWS SDK default chain; attach workload IAM rather than copying developer SSO credentials.

## Deploying from the backend repository

The [Compose bundle](../deploy/compose.yml) expects an **external PostgreSQL service**. It publishes only the frontend listener, bound to loopback by default, and stores local images in the `uploads` named volume. It does not create a database or mount workstation AWS credentials.

1. Build/test each repo and publish images to your registry. Record commit IDs and image digests together. The sample GHCR references are placeholders; packages are not created by this handoff. The frontend must have the intended `VITE_API_URL` compiled in.
2. Provision PostgreSQL 16, database, owner/migration role and a distinct non-owner runtime role. Permit private connectivity from the API and migration job. The owner needs DDL and permission for the `pgcrypto` extension. Mount the trusted DB CA; both sample URLs use `sslmode=verify-full` and `/run/secrets/db-ca.pem`.
3. Have the secret manager render runtime values from `.env.example` and owner values from `deploy/migrate.env.example` into restricted deployment-host files. Paths and `PHONE_DEFAULT_REGION` must be correct for this environment. Give container UID 10001 read access to the CA file. Attach workload IAM for SES if used.
4. Copy `deploy/.env.example` to `deploy/.env` and set image references, absolute environment/CA paths and listener settings. Supply TLS ingress, exact CORS origins and the verified real-client-IP configuration before opening public traffic.
5. Verify recovery readiness for this database and upload volume, then validate, pull and run migrations as a finite release job:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yml pull
docker compose --env-file deploy/.env -f deploy/compose.yml up --force-recreate --exit-code-from migrate migrate
```

6. After migration success, apply [runtime-grants.sql](../deploy/runtime-grants.sql) as the schema owner using `psql -v runtime_role=YOUR_RUNTIME_ROLE -f deploy/runtime-grants.sql` with your secure PostgreSQL connection configuration. The file does not create passwords/roles. Reapply after schema changes and extend its explicit table list for new migrations. The runtime role receives no schema ownership or DDL privileges; keep the migration environment out of API containers.
7. Start the application and check readiness:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yml up -d --wait api frontend
docker compose --env-file deploy/.env -f deploy/compose.yml ps
docker compose --env-file deploy/.env -f deploy/compose.yml exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).read().decode())"
```

Compose dependency startup may run the migration service again. The version table skips applied SQL, and the advisory lock serializes concurrent jobs. Migration failure must stop the release; do not bypass it with `--no-deps` to start the API.

8. On a fresh installation, create the first administrator through the interactive operator CLI, then sign in and perform the staging acceptance checks:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yml exec api python -m app.create_admin --email YOUR_EMAIL --name YOUR_NAME --mobile YOUR_MOBILE
```

There are no default administrator credentials. Do not use legacy activation as an unverified public-registration shortcut.

## Proxy and network requirements

Nginx forwards `/api/*` to `API_UPSTREAM`. API `/health`, `/ready`, `/docs` and `/openapi.json` are on private port 8000; the frontend's public health path is `/healthz`. Expose API documentation through your controlled ingress only if required. Never expose PostgreSQL publicly.

The current Nginx template sets `X-Forwarded-For` to its **direct peer**. With an outer ingress, this can be the ingress instead of the visitor. Configure the outer ingress to sanitize forwarded headers and Nginx to accept real-IP information only from that trusted ingress. Configure Uvicorn's `FORWARDED_ALLOW_IPS` for the immediate trusted Nginx/proxy network. Avoid `*` on a network reachable by arbitrary clients. Record the exact chain and verify two external clients appear as different API client IPs; otherwise OTP/login IP quotas are shared. This is an open release gate, not something CORS fixes.

The default local volume is single-host storage. For API replicas on different hosts, configure S3 and finish copying legacy local assets to the same S3 prefix, or provide shared storage for those assets. Existing image URLs need no database rewrite. Readiness is database-only; it does not test mail, S3 or an external AI provider. Follow the [storage activation and migration procedure](INTEGRATIONS.md).

## Operations and recovery

| Operation | Owner / action |
| --- | --- |
| Migrations | Release job only; `python -m app.migrate`; keep SQL history and verify `schema_migrations` includes `008_production.sql` |
| Auth retention | Scheduler runs `python -m app.maintenance --retention-days 7 --batch-size 10000` with runtime DB access; one batch per table per invocation, no unbounded loop |
| Maintenance cadence | Start with an operator-owned daily schedule; monitor deletions/backlog and adjust to retention requirements |
| API monitoring | Collect container stdout/stderr, latency, 5xx, 409/429 trends, readiness failures and DB saturation; correlate `X-Request-ID` |
| Mail monitoring | Provider delivery/bounce/complaint metrics; alert on OTP 503s and delivery latency approaching five-minute code expiry |
| Storage monitoring | Local capacity/permissions, asset 404s, storage 503s, S3 request errors and object counts |
| Recovery | PostgreSQL backups/PITR plus recovery for the selected image store; retain local-volume recovery until legacy assets are reconciled in S3; agree RPO/RTO and exercise restores |
| Rollback | Retain the previous frontend/backend image pair. Switch image references and recreate services only when the schema remains compatible. No automated down-migrations exist. Database recovery needs an operator-approved restore plan. |
| Data access | No OTP codes, passwords, hashes, database URLs or real contact lists in logs, tickets or handoff artifacts |

For scheduler integrations, execute the maintenance module in the same runtime image and inject the API runtime environment. Exit status and deletion counts are the job result. It does not delete users, questions, exam sessions or export audit history.

Migration preflight stops on duplicate normalized identities and rolls back; it does not silently merge/delete accounts. Invalid legacy mobile strings remain unchanged with a null canonical key until independently verified. The earlier local audit found nine such records and historical sessions without snapshots; refresh the inventory in the target environment without exporting contacts. See the release checklist for their treatment.

## Delivery evidence to attach

Record the release image pair/digests, source commits, migration versions, environment name, CI runs, grant verification, restored-backup evidence, verified client-IP chain, OTP delivery checks and the completed [release checklist](RELEASE_CHECKLIST.md). Repository CI checks source changes; image publishing, cloud provisioning and public deployment remain explicit platform tasks.
