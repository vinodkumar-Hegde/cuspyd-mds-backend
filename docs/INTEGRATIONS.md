# Images and email integration

## Image storage: implemented local and S3 providers

Select the provider using `STORAGE_BACKEND=local` or `STORAGE_BACKEND=s3`. S3 uses a private general-purpose bucket and workload IAM through boto3's default credential chain. No frontend changes, database migration or expiring URL persistence are required.

| Item | Implementation |
| --- | --- |
| Upload route | Administrator-only `POST /api/uploads/{bucket}`, multipart field `file` |
| Categories | `high-yield`, `subject-backgrounds`, `question-images`, `syndromes`; application categories stored in S3 object metadata |
| Validation | PNG/JPEG/WebP MIME and decoded format; Pillow verifies the image; maximum 40 million pixels and 10 MiB by default |
| Filename | Server-generated 32-character UUID hex plus `.png`, `.jpg` or `.webp` |
| Success contract | HTTP 201 with `path` and stable `publicUrl=/api/uploads/<generated-name>` in both modes |
| Local writes | Atomic file replacement in `UPLOAD_DIR`, normally `/app/uploads`, on a persistent volume |
| S3 writes | Private object at `<S3_PREFIX>/<generated-name>` with verified content type and category metadata; no public ACL |
| Read | `GET /api/uploads/{name}` first serves an existing local file; otherwise S3 mode checks the object and returns HTTP 307 to a short-lived signed HTTPS GET URL |
| Signed URL handling | Generated at read time, default lifetime 300 seconds; redirect has `Cache-Control: no-store`; never persisted in the database |
| Failures | Storage access/network/disk errors return controlled HTTP 503 without provider details; missing local files or S3 NotFound responses return 404 |
| Legacy assets | Existing UUID-named local images and PDF reads remain supported; new uploads accept images only |
| Frontend | Existing `mediaUrl()` resolves the stable API path; browser follows the S3 redirect |
| Deletion | No automated S3/local object deletion or orphan cleanup is introduced |

An S3 write failure does not fall back to a local write. This prevents successful-looking uploads that disappear on a different API replica. Local fallback is for reading existing assets during transition.

### Database image references

| Table | Column(s) | Current type |
| --- | --- | --- |
| `questions` | `image_url` | nullable text |
| `high_yield_topics` | `question_image_url`, `answer_image_url` | nullable text |
| `syndromes` | `image_url` | non-null text |
| `subject_backgrounds` | `image_url` | non-null text |

Persist the API's stable `publicUrl` in these fields. Existing external HTTPS image URLs are unchanged. There is no separate S3 object-key table: the configured prefix and stored filename determine the object key. Keep the bucket/prefix stable while those references exist, or migrate objects to the new prefix before switching settings.

## Enabling S3

| Setting | Requirement / behavior |
| --- | --- |
| `STORAGE_BACKEND` | `local` by default; set `s3` for S3 writes/reads |
| `S3_BUCKET` | Required in S3 mode; existing private general-purpose bucket |
| `S3_REGION` | Bucket region; overrides `AWS_REGION`, which overrides `AWS_DEFAULT_REGION` |
| `S3_PREFIX` | Default `uploads`; use an environment prefix such as `production/images`; empty means bucket root |
| `S3_PRESIGN_SECONDS` | Default 300, range 60–3600 seconds; actual credential expiry can shorten validity |
| `S3_KMS_KEY_ID` | Optional explicit SSE-KMS key; blank uses the bucket's default encryption |
| `UPLOAD_DIR` | Retained for legacy local reads; Docker default `/app/uploads` |

Malformed provider settings, an invalid/missing bucket name, missing S3 region, unsafe prefix or out-of-range URL lifetime fail configuration validation at startup. Bucket existence and IAM access are checked when an operation runs. The SDK uses five-second connection and ten-second read timeouts with at most three total request attempts. Readiness still checks the database, not live S3 connectivity.

Example backend runtime configuration, replacing the bucket and region:

```dotenv
STORAGE_BACKEND=s3
S3_BUCKET=your-existing-media-bucket
S3_REGION=your-bucket-region
S3_PREFIX=production/images
S3_PRESIGN_SECONDS=300
S3_KMS_KEY_ID=
```

The backend-owned `deploy/compose.yml` already reads these from the runtime environment file. The parent workspace Compose file also forwards the same settings from its `.env`. Recreate the API after environment changes. Attach a renewable workload role; no AWS access keys belong in `VITE_*` or the repository.

### Platform/IAM requirements

| Owner | Action | Acceptance |
| --- | --- | --- |
| DevOps | Provision a private bucket in the configured region; enable all four Block Public Access settings, encryption, versioning and the agreed retention policy | Reviewed infrastructure configuration and recovery test |
| DevOps | Permit `s3:PutObject` and `s3:GetObject` on the configured object prefix; see `deploy/s3-policy.json.example` | Upload, HEAD and signed GET succeed with the actual workload role |
| DevOps | For explicit/bucket-default SSE-KMS, allow required `kms:GenerateDataKey` and `kms:Decrypt` on the selected key and in its key policy | Encrypted upload and browser read succeed |
| DevOps | Provide private API egress to S3 and browser HTTPS reachability to the signed S3 endpoint | Media renders through the actual ingress and supported browsers |
| DevOps | Monitor API storage 503s, S3 errors, asset 404s, object count/cost and credential refresh | Named alert/recovery owner |
| Backend + DevOps | Copy legacy assets to identical filenames under the configured prefix before removing shared local storage | Reconciled assets and tested rollback |

The sample policy is a template, not a deployed IAM policy. Render bucket/prefix placeholders before applying it; with an empty prefix use `arn:aws:s3:::YOUR_BUCKET/*` as the object resource. The API does not need bucket creation or object deletion privileges. The `HeadObject` operation uses `s3:GetObject`; without `s3:ListBucket`, S3 may return 403 for a missing key, which this API treats as a storage 503. If exact missing-object 404 behavior is required, review the additional bucket-list permission for the dedicated environment bucket. [AWS HeadObject permission/error behavior](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/head_object.html).

The backend issues presigned `get_object` URLs at request time. A signed URL can expire earlier when its role credentials expire; keep workload credentials renewable. [AWS presigned URL API](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/generate_presigned_url.html), [URL expiration and credential lifetime](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html).

Image reads retain the existing public-by-URL application contract: anyone who knows the stable API image URL can obtain its temporary signed link. A private bucket protects direct object access; it does not add account-level content authorization. Product-required private learning content needs a separate access-policy change. Public bucket ACLs are unnecessary. [AWS Block Public Access guidance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html).

### Existing image migration

No database URL rewrite is necessary for existing `/api/uploads/<filename>` references.

1. Keep the uploads volume mounted and enable S3 with a verified bucket/region/role. New uploads go to S3; existing local files continue to load.
2. Inventory UUID-named PNG/JPG/WebP and any referenced legacy PDF files. Copy them to `<S3_PREFIX>/<same filename>` with the correct content type. Do not add category subdirectories: categories are metadata, and the resolver uses the flat filename under the prefix.
3. Use an operator migration role/tool to reconcile file counts, actual content checksums and representative rendering. S3 multipart ETags are not a universal content hash. Copy all assets to completion before removing a volume from any replica.
4. Validate a staging replica without local copies: the same stored API URLs must return signed redirects and successfully render each category. Exercise denied access and credential refresh as well as success.
5. Retain the volume for the rollback window, then remove its dependency only after reconciliation and a restore test. Until then, multi-host replicas need access to the same unmigrated legacy files.
6. For rollback, return to local mode only if every image created since enabling S3 has also been copied back, or retain the compatible S3-enabled release. Returning to local-only storage without these files would lose access to new images.

The application does not automatically copy/delete existing assets, provision a bucket, manage CDN distributions or grant IAM. Those are platform operations. No destructive cleanup or live cloud upload was performed while implementing the provider.

### Verification

The Docker suite covers local image delivery, S3 request metadata/key prefix/KMS parameters, stable URL responses, signed HTTPS redirects/expiry, legacy local reads in S3 mode, provider denial/network errors, validation/authorization before storage, and startup configuration rejection. AWS operations are stubbed through botocore; no real AWS credentials are needed for tests. Validate actual bucket permissions, encryption, browser redirects and workload credential renewal in staging before rollout.

## Email OTP: already implemented

| Flow | Endpoint / result |
| --- | --- |
| Request registration OTP | `POST /api/auth/register/request` with name/email/password/mobile and optional college/state; HTTP 202 after accepted delivery |
| Verify registration | `POST /api/auth/register/verify` with email/code; HTTP 200 creates student and profile atomically; sign in separately |
| Request password reset | `POST /api/auth/password/reset/request` with email; generic HTTP 202 response for eligible/ineligible addresses |
| Confirm password reset | `POST /api/auth/password/reset/confirm` with email/code/new_password; HTTP 200 revokes earlier sessions |
| Existing email or mobile | Registration HTTP 409; normalized email and E.164 indexes also enforce concurrency safety |
| Invalid/expired code | HTTP 400; no account creation/password change |
| Rate limit | HTTP 429; database-backed across API workers |
| Provider/configuration failure | HTTP 503; failed-send challenges are revoked |

Codes are six digits, valid for five minutes, single-use and limited to five incorrect attempts. Pending registrations expire after fifteen minutes. Only keyed code digests are stored. The implementation sends email OTP; it does **not** verify mobile ownership or send SMS.

| Rolling one-hour action quota | Per email | Per client IP |
| --- | --- | --- |
| Request code | 5, plus a 60-second request cooldown | 25 |
| Confirm code | 25, plus challenge attempt limit | 80 |
| Password login | 20 | 100 |

Registration and reset share request/confirmation quota categories. Correct trusted-proxy configuration is required for the IP column to represent real clients.

### SMTP deployment

Set `OTP_EMAIL_PROVIDER=smtp`, `OTP_SECRET`, `SMTP_HOST`, `SMTP_FROM`, `SMTP_PORT` and `SMTP_SECURITY`. Use `starttls` or `ssl` according to the provider. Set `SMTP_USERNAME` and `SMTP_PASSWORD` together if required. Permit egress to the provider; the SMTP socket timeout is ten seconds. Configure the sending domain's provider-required DNS authentication and monitor delivery.

The special plaintext Mailpit configuration is restricted to a non-production environment and the local preview hostname/port. It is not part of the image deployment template.

### SES deployment

Set `OTP_EMAIL_PROVIDER=ses`, `OTP_SECRET`, `SES_FROM_EMAIL` and `AWS_REGION` (or `AWS_DEFAULT_REGION`). The code calls SESv2 `send_email` through boto3. Attach a workload role permitting `ses:SendEmail` for the verified sending identity; constrain the sender and region in the platform policy. No SMTP username/password is used in this mode. Production workloads must have renewable role credentials instead of a developer's expiring SSO export.

Verify the sender in the selected region, configure domain authentication, handle bounces/complaints through provider monitoring and obtain production access for unrestricted recipient delivery. SES sandbox status is per region; sandbox recipients must be verified or use the simulator. [AWS SES production-access documentation](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html).

The application does not currently consume delivery webhooks, configuration-set settings or implement a durable email retry queue. Provider acceptance is not proof of inbox delivery. If such features are required, schedule explicit application work and document IAM changes.

### Staging acceptance

Use controlled staging identities to request/receive/verify a code, log in, reset a password and verify the old token is rejected. Confirm reused/expired/wrong codes fail, duplicate email/mobile receives 409 and new registrations remain students. Check provider denial yields a controlled 503 and revoke behavior. Verify client IPs through the real ingress before load testing rate limits. Do not repeatedly exercise the live provider with the unit-test suite; integration tests replace the transport.
