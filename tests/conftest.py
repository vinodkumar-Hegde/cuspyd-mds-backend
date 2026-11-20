import os
import secrets

# Integration tests only run when an explicit disposable database URL is supplied.
if os.getenv('TEST_DATABASE_URL'):
    os.environ['DATABASE_URL'] = os.environ['TEST_DATABASE_URL']
else:
    os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg://test:test@127.0.0.1:55439/mdslate_test')
os.environ.setdefault('JWT_SECRET', secrets.token_hex(32))
os.environ.setdefault('OTP_SECRET', secrets.token_hex(32))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from app import auth_email
from app.database import engine
from app.main import app
from app.migrate import migrate

RESET_TEST_DATA = '''TRUNCATE public.app_users, public.questions, public.tests, public.auth_email_challenges, public.auth_pending_registrations, public.auth_otp_rate_events, public.high_yield_topics, public.flow_chart_questions, public.syndromes, public.subject_backgrounds RESTART IDENTITY CASCADE'''


@pytest.fixture(scope='session', autouse=True)
def database():
    if not os.getenv('TEST_DATABASE_URL'):
        return
    assert make_url(engine.url).database.endswith('_test'), 'Refusing to modify a non-test database'
    if inspect(engine).has_table('app_users', schema='public'):
        with engine.begin() as connection:
            connection.execute(text('TRUNCATE public.app_users CASCADE'))
    migrate()
    migrate()  # Re-running does not replay migrations.


@pytest.fixture
def client(monkeypatch, tmp_path):
    with engine.begin() as connection:
        connection.execute(text(RESET_TEST_DATA))
    with engine.begin() as connection:
        connection.execute(text('UPDATE public.feature_settings SET is_visible=true'))
    monkeypatch.setenv('OTP_SECRET', 'test-otp-secret-with-more-than-32-characters')
    monkeypatch.setattr(auth_email, 'mail_configuration', lambda: ('test', 587, 'sender@example.org', 'starttls', '', ''))
    sent = []
    monkeypatch.setattr(auth_email, 'send_email', lambda email, code, purpose: sent.append((email, code, purpose)))
    from app.config import settings
    monkeypatch.setattr(settings(), 'upload_dir', tmp_path)
    monkeypatch.setattr(settings(), 'storage_backend', 'local')
    with TestClient(app) as test_client:
        test_client.sent = sent
        try:
            yield test_client
        finally:
            with engine.begin() as connection:
                connection.execute(text(RESET_TEST_DATA))


