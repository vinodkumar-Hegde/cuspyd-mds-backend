import os
import secrets

# Integration tests only run when an explicit disposable database URL is supplied.
if os.getenv('TEST_DATABASE_URL'):
    os.environ['DATABASE_URL'] = os.environ['TEST_DATABASE_URL']
else:
    os.environ.setdefault('DATABASE_URL', 'postgresql+psycopg://test:test@127.0.0.1:55439/mdslate_test')
os.environ.setdefault('JWT_SECRET', secrets.token_hex(32))
os.environ.setdefault('OTP_SECRET', secrets.token_hex(32))
