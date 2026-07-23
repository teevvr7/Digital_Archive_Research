"""Shared input-validation helpers used across module schemas.

Kept dependency-light: a simple length cap + format regex rather than pulling
in ``email-validator`` (the package pydantic's ``EmailStr`` requires) — adding
a new dependency for a check this simple isn't worth it.
"""

import re
from typing import Annotated

from pydantic import AfterValidator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_LENGTH = 254  # RFC 5321 mailbox length limit


def _validate_email_format(value: str) -> str:
    value = value.strip()
    if not value or len(value) > MAX_EMAIL_LENGTH or not _EMAIL_RE.match(value):
        raise ValueError("Invalid email address")
    return value


# Use as the type for any input field that must be a well-formed email address.
# For an optional field, use ``EmailField | None = None`` — pydantic only runs
# the validator on the branch of the union it matches, so ``None`` passes through.
EmailField = Annotated[str, AfterValidator(_validate_email_format)]
