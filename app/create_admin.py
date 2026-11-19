"""One-time operator CLI for a fresh installation; never a public API."""
import argparse
import getpass
import uuid

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import insert

from app.database import Sessions, table
from app.identity import normalize_email, normalize_mobile
from app.security import password_hash


def main():
    parser = argparse.ArgumentParser(description='Create one administrator on a new installation')
    parser.add_argument('--email', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--mobile', required=True)
    args = parser.parse_args()
    email = normalize_email(str(TypeAdapter(EmailStr).validate_python(args.email)))
    mobile = normalize_mobile(args.mobile)
    if not args.name.strip():
        raise SystemExit('Name is required')
    password = getpass.getpass('New administrator password (12-128 characters): ')
    confirm = getpass.getpass('Repeat password: ')
    if password != confirm or not 12 <= len(password) <= 128:
        raise SystemExit('Password confirmation or length is invalid')
    uid = uuid.uuid4()
    with Sessions.begin() as session:
        identity = {'id':uid,'email':email,'name':args.name.strip(),'mobile':mobile,'role':'admin'}
        session.execute(insert(table('app_users')).values(**identity, mobile_e164=mobile, password_hash=password_hash.hash(password)))
        session.execute(insert(table('profiles')).values(**identity))
    print('Administrator created. No default password was stored in source code.')


if __name__ == '__main__':
    main()
