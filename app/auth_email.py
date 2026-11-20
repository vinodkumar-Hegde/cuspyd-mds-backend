"""Verified student registration and password recovery (PostgreSQL + SMTP).

No external auth SDK. Codes are single-use, short-lived, HMAC protected, and
never logged or returned to the browser. Historic admins cannot self-activate.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings
from app.database import db
from app.identity import normalize_email, normalize_mobile
from app.security import password_hash


def hash_student_password(value: str) -> str:
    return password_hash.hash(value)

router = APIRouter(prefix='/api/auth', tags=['email verification'])
log = logging.getLogger('mdslate.auth.email')
RESPONSE = {'message': 'If the address is eligible, an email with instructions will be sent.'}
CODE_SECONDS = 5 * 60
PENDING_SECONDS = 15 * 60
MAX_ATTEMPTS = 5


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    mobile: str = Field(min_length=7, max_length=40)
    college: str | None = Field(default=None, max_length=160)
    state: str | None = Field(default=None, max_length=80)

    @field_validator('name', 'college', 'state', mode='before')
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('mobile')
    @classmethod
    def canonical_mobile(cls, value):
        return normalize_mobile(value)


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr


class RegisterConfirm(EmailRequest):
    code: str = Field(min_length=6, max_length=6, pattern=r'^\d{6}$')


class ResetConfirm(RegisterConfirm):
    new_password: str = Field(min_length=12, max_length=128)


def normalize(email: str) -> str:
    return normalize_email(email)


def otp_secret() -> bytes:
    value = os.getenv('OTP_SECRET', '')
    if len(value) < 32:
        raise HTTPException(503, 'Email verification is not configured')
    return value.encode('utf-8')


def digest_code(purpose: str, email: str, code: str) -> str:
    payload = f'mdslate:otp:v1:{purpose}:{email}:{code}'.encode('utf-8')
    return hmac.new(otp_secret(), payload, hashlib.sha256).hexdigest()


def digest_identifier(kind: str, value: str) -> str:
    payload = f'mdslate:rate:v1:{kind}:{value}'.encode('utf-8')
    # Login throttling must work even when outbound email is not configured.
    return hmac.new(settings().jwt_secret.encode(), payload, hashlib.sha256).hexdigest()


def new_code() -> str:
    return f'{secrets.randbelow(1_000_000):06d}'


def mail_configuration() -> tuple[str, int, str, str, str, str]:
    provider = os.getenv('OTP_EMAIL_PROVIDER', 'smtp').strip().lower()
    if provider == 'ses':
        sender = os.getenv('SES_FROM_EMAIL', '').strip()
        region = os.getenv('AWS_REGION', os.getenv('AWS_DEFAULT_REGION', '')).strip()
        if not sender or '@' not in sender or not region:
            raise HTTPException(503, 'Email verification is not configured')
        return 'ses', 0, sender, 'ses', '', ''
    if provider != 'smtp':
        raise HTTPException(503, 'Email verification is not configured')
    host = os.getenv('SMTP_HOST', '').strip()
    sender = os.getenv('SMTP_FROM', '').strip()
    mode = os.getenv('SMTP_SECURITY', 'starttls').lower()
    username = os.getenv('SMTP_USERNAME', '')
    password = os.getenv('SMTP_PASSWORD', '')
    try:
        port = int(os.getenv('SMTP_PORT', '587'))
    except ValueError:
        raise HTTPException(503, 'Email verification is not configured') from None
    preview = (settings().app_env != 'production' and os.getenv('OTP_LOCAL_PREVIEW', '') == '1'
               and host == 'otp-mailpit' and port == 1025
               and mode == 'none' and not username and not password)
    if not host or not sender or not (1 <= port <= 65535) or (mode not in ('starttls', 'ssl') and not preview):
        raise HTTPException(503, 'Email verification is not configured')
    if bool(username) != bool(password):
        raise HTTPException(503, 'Email verification is not configured')
    return host, port, sender, mode, username, password


def send_email(email: str, code: str, purpose: str) -> None:
    host, port, sender, mode, username, password = mail_configuration()
    message = EmailMessage()
    message['From'] = sender
    message['To'] = email
    message['Subject'] = 'MDSPrep email verification code'
    verb = 'verify your registration' if purpose == 'register' else 'reset your password'
    message.set_content(
        f'Your MDSPrep code to {verb} is: {code}\n\n'
        f'It expires after {CODE_SECONDS // 60} minutes and can only be used once.\n'
        'If you did not request this code, ignore this message.\n'
    )
    if mode == 'ses':
        # AWS SDK uses IAM/SSO credential resolution, not SMTP passwords.
        import boto3
        boto3.client('sesv2', region_name=os.getenv('AWS_REGION', os.getenv('AWS_DEFAULT_REGION'))).send_email(
            FromEmailAddress=sender,
            Destination={'ToAddresses': [email]},
            Content={'Simple': {
                'Subject': {'Data': message['Subject'], 'Charset': 'UTF-8'},
                'Body': {'Text': {'Data': message.get_content(), 'Charset': 'UTF-8'}}
            }},
        )
        return
    context = ssl.create_default_context()
    if mode == 'ssl':
        with smtplib.SMTP_SSL(host, port, timeout=10, context=context) as smtp:
            if username: smtp.login(username, password)
            smtp.send_message(message)
    elif mode == 'none':
        # Only permitted for the local Docker Mailpit preview. No internet delivery.
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            if username: smtp.login(username, password)
            smtp.send_message(message)


def ip_of(request: Request) -> str:
    # Do NOT trust user-controlled X-Forwarded-For unless your ASGI proxy is configured.
    return request.client.host if request.client else 'unknown'


def rate_limit(session: Session, email: str, ip: str, action: str, *, cooldown: bool = True) -> None:
    """Database-backed limiter for every request, including unknown email addresses.

    The advisory lock serializes concurrent attempts on the same IP/email.
    Only keyed digests (not raw addresses/IPs) are retained in rate history.
    """
    ed = digest_identifier('email', email)
    ipd = digest_identifier('ip', ip)
    for lock_id in sorted((f'otp:email:{ed}', f'otp:ip:{ipd}')):
        session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))'), {'k': lock_id})
    # Rolling limits. Request: 5/hr/email, 25/hr/IP, 60-sec cooldown.
    # Confirm: 25/hr/email, 80/hr/IP, individual challenge allows max 5 failures.
    # Password login: 20/hr/email and 100/hr/IP; rate events persist for audit.
    max_email, max_ip = ((5, 25) if action == 'request' else
                         (25, 80) if action == 'confirm' else (20, 100))
    email_hits = session.execute(text('''
        SELECT count(*) FROM public.auth_otp_rate_events
        WHERE email_digest=:ed AND action=:action AND created_at > now() - interval '1 hour'
    '''), {'ed': ed, 'action': action}).scalar_one()
    ip_hits = session.execute(text('''
        SELECT count(*) FROM public.auth_otp_rate_events
        WHERE ip_digest=:ipd AND action=:action AND created_at > now() - interval '1 hour'
    '''), {'ipd': ipd, 'action': action}).scalar_one()
    if email_hits >= max_email or ip_hits >= max_ip:
        raise HTTPException(429, 'Too many requests. Try again later.')
    if action == 'request' and cooldown:
        recent_request = session.execute(text('''
          SELECT count(*) FROM public.auth_otp_rate_events
          WHERE email_digest=:ed AND action='request' AND created_at > now() - interval '60 seconds'
        '''), {'ed': ed}).scalar_one()
        if recent_request:
            raise HTTPException(429, 'Please wait 60 seconds before requesting another code.')
    session.execute(text('''
      INSERT INTO public.auth_otp_rate_events (email_digest, ip_digest, action)
      VALUES (:ed, :ipd, :action)
    '''), {'ed': ed, 'ipd': ipd, 'action': action})


def eligible_student(account: dict | None) -> bool:
    return bool(account and account['role'] == 'student' and
                account['email_recovery_allowed'] and
                (account['is_active'] or account['password_reset_required']))


def get_user(session: Session, email: str):
    result = session.execute(text('''
        SELECT id, role, email_recovery_allowed, is_active, password_reset_required
        FROM public.app_users WHERE lower(btrim(email))=:email
    '''), {'email': email}).mappings().first()
    return dict(result) if result else None


def save_challenge(session: Session, email: str, purpose: str, code: str) -> None:
    session.execute(text('''
        INSERT INTO public.auth_email_challenges
           (email, purpose, code_digest, attempts, expires_at, issued_at)
        VALUES (:email, :purpose, :code_digest, 0, now() + make_interval(secs => :code_seconds), now())
        ON CONFLICT (email, purpose) DO UPDATE
        SET code_digest=EXCLUDED.code_digest, attempts=0,
            expires_at=EXCLUDED.expires_at, issued_at=EXCLUDED.issued_at
    '''), {'email': email, 'purpose': purpose,
           'code_digest': digest_code(purpose, email, code), 'code_seconds': CODE_SECONDS})


def invalidate_sent_code(session: Session, email: str, purpose: str, code: str) -> None:
    with session.begin():
        session.execute(text('''
            DELETE FROM public.auth_email_challenges
            WHERE email=:email AND purpose=:purpose AND code_digest=:digest
        '''), {'email': email, 'purpose': purpose,
               'digest': digest_code(purpose, email, code)})


def checked_challenge(session: Session, email: str, purpose: str, code: str) -> bool:
    record = session.execute(text('''
        SELECT code_digest, attempts, expires_at FROM public.auth_email_challenges
        WHERE email=:email AND purpose=:purpose FOR UPDATE
    '''), {'email': email, 'purpose': purpose}).mappings().first()
    if not record:
        # Uniform timing of missing challenge comparisons.
        hmac.compare_digest(digest_code(purpose, email, code), digest_code(purpose, email, '000000'))
        return False
    if record['attempts'] >= MAX_ATTEMPTS or record['expires_at'] <= datetime.now(timezone.utc):
        return False
    correct = hmac.compare_digest(record['code_digest'], digest_code(purpose, email, code))
    if not correct:
        session.execute(text('''
          UPDATE public.auth_email_challenges SET attempts=attempts + 1
          WHERE email=:email AND purpose=:purpose
        '''), {'email': email, 'purpose': purpose})
    return correct


def mark_consumed(session: Session, email: str, purpose: str) -> None:
    session.execute(text('''
        DELETE FROM public.auth_email_challenges WHERE email=:email AND purpose=:purpose
    '''), {'email': email, 'purpose': purpose})


def deliver_or_revoke(session: Session, email: str, purpose: str, code: str) -> None:
    try:
        send_email(email, code, purpose)
    except (smtplib.SMTPException, OSError, ssl.SSLError, BotoCoreError, ClientError):
        log.error('Email delivery failure for %s', purpose)
        invalidate_sent_code(session, email, purpose, code)
        raise HTTPException(503, 'Email service temporarily unavailable') from None


@router.post('/register/request', status_code=status.HTTP_202_ACCEPTED)
def request_registration(body: RegistrationRequest, request: Request, session: Session = Depends(db)):
    otp_secret(); mail_configuration()
    email = normalize(str(body.email))
    code = new_code()
    with session.begin():
        conflict = registration_conflict(session, email, body.mobile)
        rate_limit(session, email, ip_of(request), 'request', cooldown=not bool(conflict))
        if not conflict:
            session.execute(text('''
              INSERT INTO public.auth_pending_registrations
                (email, password_hash, name, mobile, college, state, expires_at)
              VALUES (:email, :hash, :name, :mobile, :college, :state, now() + make_interval(secs => :pending_seconds))
              ON CONFLICT (email) DO UPDATE SET
                password_hash=EXCLUDED.password_hash, name=EXCLUDED.name,
                mobile=EXCLUDED.mobile, college=EXCLUDED.college,
                state=EXCLUDED.state, expires_at=EXCLUDED.expires_at
            '''), {'email': email, 'hash': hash_student_password(body.password),
                   'name': body.name.strip(), 'mobile': body.mobile, 'college': body.college,
                   'state': body.state, 'pending_seconds': PENDING_SECONDS})
            save_challenge(session, email, 'register', code)
    if conflict:
        raise HTTPException(409, conflict)
    deliver_or_revoke(session, email, 'register', code)
    return {'message': 'A verification code has been sent to your email.'}


def registration_conflict(session: Session, email: str, mobile: str) -> str | None:
    # Indexed checks provide helpful errors; unique indexes close concurrent races.
    if get_user(session, email):
        return 'This email address is already registered. Sign in or reset your password.'
    existing = session.execute(text('SELECT 1 FROM public.app_users WHERE mobile_e164=:mobile LIMIT 1'),
                               {'mobile': mobile}).first()
    if existing:
        return 'This mobile number is already registered. Use a different mobile number.'
    return None


@router.post('/register/verify')
def verify_registration(body: RegisterConfirm, request: Request, session: Session = Depends(db)):
    email = normalize(str(body.email))
    try:
        with session.begin():
            rate_limit(session, email, ip_of(request), 'confirm')
            valid = checked_challenge(session, email, 'register', body.code)
            pending = session.execute(text('''
                SELECT password_hash, name, mobile, college, state, expires_at
                FROM public.auth_pending_registrations WHERE email=:email FOR UPDATE
            '''), {'email': email}).mappings().first()
            conflict = (registration_conflict(session, email, normalize_mobile(pending['mobile']))
                        if valid and pending and pending['expires_at'] > datetime.now(timezone.utc) else None)
            if not valid or not pending or pending['expires_at'] <= datetime.now(timezone.utc) or conflict:
                # Commit failed attempt counter/rate event, then reject below.
                verified = False
            else:
                uid = uuid.uuid4()
                session.execute(text('''
                  INSERT INTO public.app_users
                    (id,email,password_hash,name,mobile_e164,college,state,role,is_active,password_reset_required,token_version)
                  VALUES (:id,:email,:hash,:name,:mobile,:college,:state,'student',true,false,0)
                '''), {'id': uid, 'email': email, 'hash': pending['password_hash'],
                       'name': pending['name'], 'mobile': pending['mobile'], 'college': pending['college'], 'state': pending['state']})
                mark_consumed(session, email, 'register')
                session.execute(text('DELETE FROM public.auth_pending_registrations WHERE email=:email'), {'email': email})
                verified = True
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, 'This email address or mobile number is already registered.') from None
    if conflict:
        raise HTTPException(409, conflict)
    if not verified:
        raise HTTPException(400, 'Invalid or expired verification code')
    return {'message': 'Email verified. You may now sign in.'}


@router.post('/password/reset/request', status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(body: EmailRequest, request: Request, session: Session = Depends(db)):
    otp_secret(); mail_configuration()
    email = normalize(str(body.email))
    code = new_code()
    should_send = False
    with session.begin():
        rate_limit(session, email, ip_of(request), 'request')
        if eligible_student(get_user(session, email)):
            save_challenge(session, email, 'reset', code)
            should_send = True
    if should_send:
        deliver_or_revoke(session, email, 'reset', code)
    return RESPONSE


@router.post('/password/reset/confirm')
def confirm_password_reset(body: ResetConfirm, request: Request, session: Session = Depends(db)):
    email = normalize(str(body.email))
    try:
        with session.begin():
            rate_limit(session, email, ip_of(request), 'confirm')
            valid = checked_challenge(session, email, 'reset', body.code)
            account = get_user(session, email)
            if not valid or not eligible_student(account):
                reset = False
            else:
                result = session.execute(text('''
                  UPDATE public.app_users SET password_hash=:hash, is_active=true,
                     password_reset_required=false, token_version=token_version + 1
                  WHERE lower(btrim(email))=:email AND role='student'
                    AND email_recovery_allowed=true
                    AND (is_active OR password_reset_required)
                '''), {'email': email, 'hash': hash_student_password(body.new_password)})
                reset = result.rowcount == 1
                if reset:
                    mark_consumed(session, email, 'reset')
    except IntegrityError:
        session.rollback()
        log.error('Password reset database integrity conflict')
        raise HTTPException(503, 'Password reset temporarily unavailable') from None
    if not reset:
        raise HTTPException(400, 'Invalid or expired verification code')
    return {'message': 'Password updated. Please sign in with your new password.'}


def login_gate(session: Session, email: str, ip: str) -> None:
    # Password login is also rate-limited across multiple API workers.
    rate_limit(session, normalize(email), ip, 'login')
