"""Local DB-operator account recovery. Not a public password-reset endpoint.

Usage inside Docker (interactive TTY):
  docker compose exec api python -m app.activate_local_account --email user@example.com
Identity must be verified OUTSIDE this CLI before proceeding.
"""
from __future__ import annotations

import argparse
import getpass
from sqlalchemy import MetaData, Table, select, update
from app.database import Sessions, engine
from app.security import password_hash


def main():
    parser = argparse.ArgumentParser(description='Locally activate ONE identity-verified account')
    pick = parser.add_mutually_exclusive_group(required=True)
    pick.add_argument('--email', help='Existing migrated email (not a new signup)')
    pick.add_argument('--id', help='Existing migrated UUID')
    parser.add_argument('--grant-admin', action='store_true', help='Grant admin only to a verified historic admin')
    args = parser.parse_args()
    users = Table('app_users', MetaData(), autoload_with=engine)
    with Sessions() as session:
        q = select(users).where(users.c.email == args.email.lower().strip()) if args.email else select(users).where(users.c.id == args.id)
        record = session.execute(q).mappings().first()
        if not record:
            raise SystemExit('No matching migrated account found. No changes made.')
        if record['is_active'] and not record['password_reset_required']:
            raise SystemExit('Account already active. No changes made.')
        if args.grant_admin and record['legacy_role'] != 'admin':
            raise SystemExit('Account was not a historic admin. Refusing automatic promotion.')
        print('User:', record['email'] or '(no email)', 'ID:', record['id'], 'legacy_role:', record['legacy_role'])
        print('You MUST independently verify that this account belongs to the intended person.')
        choice = input('Type the full account UUID to confirm verified identity: ').strip()
        if choice != str(record['id']):
            raise SystemExit('Confirmation mismatch. No changes made.')
        pw = getpass.getpass('New password (at least 12 characters): ')
        pw2 = getpass.getpass('Repeat password: ')
        if pw != pw2 or len(pw) < 12 or len(pw) > 128:
            raise SystemExit('Password confirmation or length invalid. No changes made.')
        role = 'admin' if args.grant_admin else 'student'
        session.execute(update(users).where(users.c.id == record['id']).values(
            password_hash=password_hash.hash(pw), is_active=True,
            password_reset_required=False, role=role, token_version=users.c.token_version + 1))
        session.commit()
        print('One verified local account activated as',role+'. Other migrated accounts remain disabled.')

if __name__ == '__main__': main()
