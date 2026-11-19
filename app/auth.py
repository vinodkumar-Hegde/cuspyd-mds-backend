from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import db, table
from app.identity import normalize_email
from app.security import DUMMY_HASH, authenticated, issue_token, password_hash, public_user

router = APIRouter(prefix='/api/auth', tags=['authentication'])


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


@router.post('/login')
def login(body: Credentials, request: Request, session: Session = Depends(db)):
    from app.auth_email import ip_of, login_gate
    email = normalize_email(str(body.email))
    with session.begin():
        login_gate(session, email, ip_of(request))
        users = table('app_users')
        user = session.execute(select(users).where(func.lower(func.btrim(users.c.email)) == email)).mappings().first()
        try:
            matches = password_hash.verify(body.password, user['password_hash'] if user and user['password_hash'] else DUMMY_HASH)
        except (UnknownHashError, ValueError):
            matches = False
        valid = bool(matches and user and user['is_active'] and not user['password_reset_required'])
    if not valid:
        raise HTTPException(401, 'Invalid email or password')
    return {'access_token': issue_token(str(user['id']), user['token_version']), 'user': public_user(user)}


@router.get('/me')
def me(user: dict = Depends(authenticated)):
    return public_user(user)


@router.post('/logout', status_code=204)
def logout(user: dict = Depends(authenticated), session: Session = Depends(db)):
    users = table('app_users')
    session.execute(users.update().where(users.c.id == user['id']).values(token_version=users.c.token_version + 1))
    session.commit()
