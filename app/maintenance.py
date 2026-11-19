"""Bounded retention job, run by an operator scheduler rather than API requests."""
import argparse
from sqlalchemy import text
from app.database import engine

CLEANUPS = (
    ('auth_email_challenges', "expires_at < now() - make_interval(days => :days)", 'ctid'),
    ('auth_pending_registrations', "expires_at < now() - make_interval(days => :days)", 'ctid'),
    ('auth_otp_rate_events', "created_at < now() - make_interval(days => :days)", 'ctid'),
)


def main():
    parser = argparse.ArgumentParser(description='Delete one bounded batch of expired auth data')
    parser.add_argument('--retention-days', type=int, default=7)
    parser.add_argument('--batch-size', type=int, default=10000)
    args = parser.parse_args()
    if not 1 <= args.retention_days <= 365 or not 1 <= args.batch_size <= 100000:
        raise SystemExit('Use retention-days 1-365 and batch-size 1-100000')
    with engine.begin() as connection:
        for name, condition, key in CLEANUPS:
            # Identifiers and conditions are constants; only values are parameters.
            result = connection.execute(text(f'''DELETE FROM public.{name} WHERE {key} IN (
                SELECT {key} FROM public.{name} WHERE {condition} LIMIT :batch
            )'''), {'days':args.retention_days, 'batch':args.batch_size})
            print(f'{name}: removed {result.rowcount} expired records')


if __name__ == '__main__':
    main()
