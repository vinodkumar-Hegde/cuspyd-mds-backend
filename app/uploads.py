"""Bounded, validated file uploads; the API owns filenames and storage paths."""
import io
from pathlib import Path
import re
import uuid
import warnings

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.security import admin
from app.storage import image_source, save_image, StorageUnavailable

router = APIRouter(prefix='/api/uploads', tags=['uploads'])
BUCKETS = frozenset({'high-yield', 'subject-backgrounds', 'question-images', 'syndromes'})
TYPES = {'image/png': ('PNG', '.png'), 'image/jpeg': ('JPEG', '.jpg'), 'image/webp': ('WEBP', '.webp')}


def validate_image(blob: bytes, mime: str):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(blob)) as image:
                if image.format != TYPES[mime][0] or image.width * image.height > 40_000_000:
                    raise ValueError('Invalid image')
                image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise HTTPException(422, 'Upload a valid PNG, JPEG or WebP image') from None


@router.post('/{bucket}', status_code=201)
async def upload(bucket: str, file: UploadFile = File(...), actor: dict = Depends(admin)):
    if bucket not in BUCKETS or file.content_type not in TYPES:
        raise HTTPException(422, 'Unsupported image type or upload category')
    blob = bytearray()
    try:
        while chunk := await file.read(64 * 1024):
            blob.extend(chunk)
            if len(blob) > settings().max_upload_bytes:
                raise HTTPException(413, 'File exceeds the upload size limit')
        await run_in_threadpool(validate_image, bytes(blob), file.content_type)
        name = uuid.uuid4().hex + TYPES[file.content_type][1]
        await run_in_threadpool(save_image, name, bytes(blob), file.content_type, bucket)
    except StorageUnavailable:
        raise HTTPException(503, 'Image storage temporarily unavailable') from None
    finally:
        await file.close()
    return {'path': name, 'publicUrl': f'/api/uploads/{name}'}


@router.get('/{name}')
def serve_upload(name: str):
    if not re.fullmatch(r'[0-9a-f]{32}\.(png|jpg|webp|pdf)', name):
        raise HTTPException(404, 'File not found')
    try:
        source = image_source(name)
    except FileNotFoundError:
        raise HTTPException(404, 'File not found')
    except StorageUnavailable:
        raise HTTPException(503, 'Image storage temporarily unavailable') from None
    if isinstance(source, Path):
        return FileResponse(source, headers={'X-Content-Type-Options': 'nosniff'})
    return RedirectResponse(source, status_code=307, headers={'Cache-Control': 'no-store'})
