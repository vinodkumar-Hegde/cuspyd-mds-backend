"""Authentication dependencies without circular app imports."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import db, table

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash('unused-comparison-password')


def issue_token(user_id: str, token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({'sub': user_id, 'ver': token_version, 'iat': now,
                       'exp': now + timedelta(minutes=settings().access_token_minutes),
                       'iss': 'mdslate-api', 'aud': 'mdslate-web'}, settings().jwt_secret, algorithm='HS256')


def authenticated(request: Request, session: Session = Depends(db)) -> dict:
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
    try:
        claims = jwt.decode(header[7:], settings().jwt_secret, algorithms=['HS256'],
                            issuer='mdslate-api', audience='mdslate-web',
                            options={'require': ['sub', 'exp', 'iat', 'ver']})
        uid = uuid.UUID(claims['sub'])
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(401, 'Invalid or expired session') from None
    users = table('app_users')
    user = session.execute(select(users).where(users.c.id == uid)).mappings().first()
    if (not user or not user['is_active'] or user['password_reset_required'] or
            not user['password_hash'] or claims['ver'] != user['token_version']):
        raise HTTPException(401, 'Invalid or expired session')
    return dict(user)


def admin(user: dict = Depends(authenticated)) -> dict:
    if user['role'] != 'admin':
        raise HTTPException(403, 'Administrator access required')
    return user


def feature(key: str):
    def permitted(user: dict = Depends(authenticated), session: Session = Depends(db)):
        if user['role'] != 'admin':
            flags = table('feature_settings')
            visible = session.execute(select(flags.c.is_visible).where(flags.c.feature_key == key)).scalar_one_or_none()
            if visible is False:
                raise HTTPException(403, 'This feature is currently unavailable')
        return user
    return permitted


def public_user(user):
    result = {key: user.get(key) for key in ('id', 'email', 'name', 'role', 'college', 'state')}
    result['mobile'] = user.get('mobile_e164')
    return result
