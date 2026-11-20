"""Local/S3 image storage. Database references stay stable across providers."""
from functools import lru_cache
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings

log = logging.getLogger('mdslate.storage')


class StorageUnavailable(Exception):
    """An operational storage failure; provider details must not reach clients."""


@lru_cache(maxsize=1)
def s3_client():
    return boto3.session.Session().client(
        's3', region_name=settings().storage_region,
        config=Config(signature_version='s3v4', connect_timeout=5, read_timeout=10,
                      retries={'mode': 'standard', 'total_max_attempts': 3}),
    )


def object_key(name: str) -> str:
    prefix = settings().s3_prefix
    return f'{prefix}/{name}' if prefix else name


def unavailable(operation: str, exc: Exception):
    # Never log AWS responses, signed URLs, credentials or filesystem paths.
    log.warning('Image storage failed operation=%s backend=%s error=%s',
                operation, settings().storage_backend, type(exc).__name__)
    raise StorageUnavailable from None


def save_image(name: str, blob: bytes, content_type: str, category: str) -> None:
    cfg = settings()
    temporary = None
    try:
        if cfg.storage_backend == 's3':
            encryption = ({'ServerSideEncryption': 'aws:kms', 'SSEKMSKeyId': cfg.s3_kms_key_id}
                          if cfg.s3_kms_key_id else {})
            s3_client().put_object(
                Bucket=cfg.s3_bucket, Key=object_key(name), Body=blob,
                ContentType=content_type, Metadata={'category': category}, **encryption,
            )
        else:
            cfg.upload_dir.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=cfg.upload_dir, prefix='.upload-', delete=False) as output:
                temporary = Path(output.name)
                output.write(blob)
            temporary.replace(cfg.upload_dir / name)
    except (BotoCoreError, ClientError, OSError) as exc:
        unavailable('write', exc)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                log.warning('Could not remove temporary upload file')


def image_source(name: str) -> Path | str:
    """Read legacy local files first, or return a fresh private-S3 signed URL."""
    cfg = settings()
    try:
        local = cfg.upload_dir / name
        if local.is_file():
            return local
        if cfg.storage_backend == 'local':
            raise FileNotFoundError(name)
        params = {'Bucket': cfg.s3_bucket, 'Key': object_key(name)}
        s3_client().head_object(**params)
        return s3_client().generate_presigned_url(
            'get_object', Params=params, ExpiresIn=cfg.s3_presign_seconds, HttpMethod='GET',
        )
    except ClientError as exc:
        if str(exc.response.get('Error', {}).get('Code')) in ('404', 'NoSuchKey', 'NotFound'):
            raise FileNotFoundError(name) from None
        unavailable('read', exc)
    except FileNotFoundError:
        raise
    except (BotoCoreError, OSError) as exc:
        unavailable('read', exc)
