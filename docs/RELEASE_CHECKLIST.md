# Release checklist and open review findings

Status: **production sign-off pending**. Baseline automated tests passed during the preceding code review, but six additional review scenarios exposed defects. This handoff documents them; it does not change application behavior or close them.

## Engineering gates

| ID / priority | Finding and source | Required fix / acceptance |
| --- | --- | --- |
| R1 / P1 | `app/routes_v1.py:db_test`, `image_questions`: any question with an image becomes a virtual active exam, including questions referenced by draft/future tests | Define image-practice publication eligibility. A student must not retrieve/submit unpublished test questions through the image route and obtain the answer key before release. Test both routes together. |
| R2 / P1 | `app/auth_email.py:ip_of`, backend Docker/Uvicorn defaults, frontend Nginx headers: proxy IP can become the shared rate-limit identity | Configure trusted real-client-IP handling through ingress, Nginx and Uvicorn. Demonstrate two real external IPs receive distinct quota accounting and spoofed headers cannot bypass it. |
| R3 / P1 | `app/routes_v1.py:exam_history_result`: legacy results without `result_snapshot` call the active-exam lookup | Separate historical reads from publication state. An owned, completed legacy attempt must remain viewable after test archival. Plan backfill carefully; present-day answers cannot recreate a guaranteed historical snapshot. |
| R4 / P2 | `app/routes_v1.py:submit_exam`: exam availability/question reads occur before the idempotency lookup | A retry with the same user/exam/request ID must return the persisted result after archival or question edits; reusing the ID for a different exam remains 409. |
| R5 / P2 | High-yield UI derives subjects from one global page; several content/admin list screens have fixed caps | Add pagination and authoritative subject availability. A subject with older content must remain selectable beyond the first 500 records; verify other capped lists at realistic scale. |
| R6 / P2 | `app/routes_v1.py:ai_generate_questions`: provider list items use `.get()` before validating each item is an object | Validate provider output per item. A response such as `[42]` must return controlled invalid-provider-data handling, not an unhandled 500. |

All six require closure before declaring the application production ready, or an explicit product/engineering disposition with affected functionality disabled and evidence. R2 spans application and platform configuration; it is not resolved merely by adding an environment variable to an example file.

The earlier local audit found 121 completed historical sessions without snapshots and nine invalid legacy mobile strings. These are environment-specific observations, not fresh-install defaults. Refresh counts on the target database. Preserve existing data, obtain verified mobile corrections and record who owns historical-result remediation. No real contacts or account identifiers are embedded in this handoff.

## Platform gates

- [ ] Frontend/backend commits and immutable image references recorded together; registry pull access verified.
- [ ] Separate repo CI checks pass; image vulnerability review and branch protections configured by DevOps.
- [ ] HTTPS DNS/ingress configured; exact frontend CORS origins and frontend build-time API origin verified.
- [ ] Trusted proxy chain verified against real clients and spoofed forwarded headers (R2).
- [ ] PostgreSQL 16 provisioned privately; trusted CA and hostname verification pass.
- [ ] Migration job succeeds; required migration recorded; owner credentials absent from API runtime.
- [ ] Runtime role is not a schema owner and has no DDL grant; explicit table/sequence grants applied after migrations.
- [ ] Distinct random JWT/OTP secrets injected securely; credential rotation and session implications recorded.
- [ ] SMTP/SES sender/domain and delivery operational; SES production access/quotas appropriate if used.
- [ ] Controlled registration/reset OTP and duplicate email/mobile checks pass through the public staging ingress.
- [ ] Upload volume persists through API replacement; permissions for UID 10001 and recovery verified.
- [ ] Image provider selected: local mode has a persistent volume; S3 mode has verified bucket/region/IAM, signed browser reads and legacy-asset reconciliation before volume removal.
- [ ] Readiness, 5xx, quota errors, email delivery, DB capacity and storage failures have named alert owners.
- [ ] Bounded auth cleanup scheduled; retention policy and backlog monitoring agreed.
- [ ] PostgreSQL and current image-store recovery tested; RPO/RTO and compatible-image rollback documented.

## Test evidence

| Verification | Evidence / limit |
| --- | --- |
| Current backend checks | `deploy/compose.test.yml` passed lint and all 53 tests in Docker, including S3 SDK contract/failure tests and its own PostgreSQL 16 instance |
| Handoff frontend checks | Independent Node build and final Nginx image built successfully; TypeScript validation and all 6 API client tests passed in Docker |
| Handoff schema dictionary | Read-only catalog metadata confirmed 17 managed tables and 114 columns; no application rows exported |
| Handoff deployment configuration | Compose parsed successfully with placeholder-only environment/CA files; external cloud database TLS and live deployment remain environment acceptance work |
| Handoff role grants | Applied to an isolated non-owner role: all managed tables readable, sequences usable, readiness selectable; schema CREATE, migration UPDATE and audit DELETE absent |
| Prior dependency review | Frontend audit and pinned backend dependency audit reported no known vulnerabilities at that check; rerun for the release |
| Review edge scenarios | Six regressions above remained open despite the passing baseline; add meaningful regression coverage with each fix |
| Interactive UI | Browser-control host was unavailable during the prior review; a full interactive walkthrough is still required |
| Cloud integrations | No S3 provision/upload or production SMTP/SES delivery is certified by unit/integration tests |
| S3 implementation | Provider selection, prefix/KMS options, stable API URLs, signed reads, validation/permissions and legacy local fallback pass offline SDK tests; real bucket/IAM activation remains a platform acceptance check |
| Local API rollout | Updated API image rebuilt with existing SES settings; active provider remains local; direct readiness and frontend HTTP checks passed, with unauthenticated `/api/auth/me` correctly returning 401 |

Run backend checks using `deploy/compose.test.yml` in an isolated project. That database is disposable, has no persistent volume or published port, and uses public test-only credentials. The integration suite refuses database names that do not end in `_test` and clears its fixtures. Never point it at a shared application database or a staging database with data to retain.

## Release record

| Field | Operator entry |
| --- | --- |
| Environment / timestamp | Pending |
| Backend commit / image digest | Pending |
| Frontend commit / image digest / `VITE_API_URL` | Pending |
| Migration versions and role-grant evidence | Pending |
| Engineering gates R1–R6 | Pending |
| OTP delivery and image storage checks | Pending |
| Restore exercise / RPO / RTO | Pending |
| Previous compatible image pair | Pending |
| Release owner and engineering acceptance | Pending |
