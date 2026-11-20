"""Versioned, transactional migrations: python -m app.migrate.

Preflight prevents silent merging/deletion of duplicate identities. Invalid legacy
mobile strings are retained unchanged without a canonical key; new registrations
must still pass strict mobile validation. No replacement numbers are invented.
"""
from pathlib import Path
import logging
from sqlalchemy import inspect, text

from app.database import engine, table
from app.identity import normalize_email, normalize_mobile

log = logging.getLogger('mdslate.migrations')


def migrate():
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('mdslate:migrations', 0))"))
        tables = inspect(connection).get_table_names(schema='public')
        connection.execute(text('CREATE TABLE IF NOT EXISTS public.schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())'))
        applied = set(connection.execute(text('SELECT version FROM public.schema_migrations')).scalars())
        canonical = []
        invalid_mobile_count = 0
        if 'app_users' in tables and '008_production.sql' not in applied:
            users = connection.execute(text('SELECT id, email, mobile FROM public.app_users')).mappings().all()
            emails, mobiles = set(), set()
            for user in users:
                email = normalize_email(user['email']) if user['email'] else None
                mobile = None
                if user['mobile'] and user['mobile'].strip():
                    try:
                        mobile = normalize_mobile(user['mobile'])
                    except ValueError:
                        invalid_mobile_count += 1
                if (email and email in emails) or (mobile and mobile in mobiles):
                    raise RuntimeError('Duplicate legacy email/mobile identities found; resolve ownership before migrating')
                if email: emails.add(email)
                if mobile: mobiles.add(mobile)
                canonical.append({'id': user['id'], 'mobile': mobile})
        if invalid_mobile_count:
            log.warning('%d invalid legacy mobile values preserved unchanged without canonical phone keys; new registration validation remains strict', invalid_mobile_count)
        for path in sorted((Path(__file__).resolve().parents[1] / 'sql').glob('*.sql')):
            if path.name in applied:
                continue
            connection.exec_driver_sql(path.read_text())
            if path.name == '008_production.sql' and canonical:
                connection.execute(text('UPDATE public.app_users SET mobile_e164=:mobile WHERE id=:id'), canonical)
            if path.name == '009_canonical_runtime.sql':
                from migrations.canonical import migrate as canonical_runtime
                canonical_runtime(connection)
            connection.execute(text('INSERT INTO public.schema_migrations (version) VALUES (:version)'), {'version': path.name})
            print(f'Applied {path.name}')
    table.cache_clear()


if __name__ == '__main__':
    migrate()
