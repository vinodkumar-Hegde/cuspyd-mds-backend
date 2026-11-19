"""Canonical identity representations shared by registration and migrations."""
import phonenumbers

from app.config import settings


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_mobile(value: str) -> str:
    try:
        number = phonenumbers.parse(value.strip(), settings().phone_default_region)
    except phonenumbers.NumberParseException:
        raise ValueError('Enter a valid mobile number, including its country code') from None
    if (number.extension or not phonenumbers.is_valid_number(number) or
            phonenumbers.number_type(number) not in
            (phonenumbers.PhoneNumberType.MOBILE, phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE)):
        raise ValueError('Enter a valid mobile number, including its country code')
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
