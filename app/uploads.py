"""Bounded, validated file uploads; the API owns filenames and storage paths."""
import io
import re
import uuid
import warnings

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.security import admin

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
        directory = settings().upload_dir
        await run_in_threadpool(directory.mkdir, parents=True, exist_ok=True)
        await run_in_threadpool((directory / name).write_bytes, blob)
    finally:
        await file.close()
    return {'path': name, 'publicUrl': f'/api/uploads/{name}'}


@router.get('/{name}')
def serve_upload(name: str):
    if not re.fullmatch(r'[0-9a-f]{32}\.(png|jpg|webp|pdf)', name):
        raise HTTPException(404, 'File not found')
    path = settings().upload_dir / name
    if not path.is_file():
        raise HTTPException(404, 'File not found')
    return FileResponse(path, headers={'X-Content-Type-Options': 'nosniff'})
