# Cuspyd MDS backend

FastAPI owns PostgreSQL access, authentication, email OTP, scoring, uploads and administrator operations. The [frontend](https://github.com/vinodkumar-Hegde/cuspyd-mds-frontend) communicates through HTTP only. Python runs in Docker; a host `.venv` is unnecessary.

| Handoff document | Contents |
| --- | --- |
| [DevOps handoff](docs/DEVOPS_HANDOFF.md) | Repository structure, configuration, deployment, operations and ownership |
| [Database dictionary](docs/DATABASE.md) | Tables, columns, keys, indexes and JSON contracts |
| [S3 and email integrations](docs/INTEGRATIONS.md) | Configurable local/S3 image storage and SMTP/SES OTP |
| [Release checklist](docs/RELEASE_CHECKLIST.md) | Open review findings, acceptance checks and release evidence |

The handoff includes deployment templates, **not production sign-off**. Image storage supports local files or a private S3 bucket selected by runtime configuration. DevOps provides the bucket, region and IAM role. Resolve the release checklist and validate the cloud environment before public rollout.

Build the independent API image from this repository root:

```sh
docker build --target runtime -t cuspyd-mds-backend:local .
```

Run lint and integration tests against a disposable PostgreSQL 16 database:

```sh
docker compose -p mdslate-backend-test -f deploy/compose.test.yml run --build --rm test
docker compose -p mdslate-backend-test -f deploy/compose.test.yml down --volumes
```

`sql/*.sql` and `python -m app.migrate` are the schema authority. Do not flatten, delete or renumber existing migrations. `/docs` and `/openapi.json` describe the running API; `/health` checks the process and `/ready` checks database migration readiness.
