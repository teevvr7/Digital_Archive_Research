"""Shared input-validation helpers used across module schemas.

Kept dependency-light: a simple length cap + format regex rather than pulling
in ``email-validator`` (the package pydantic's ``EmailStr`` requires) — adding
a new dependency for a check this simple isn't worth it.
"""

# re is the standard-library regex module — used to check email shape.
import re

# Annotated lets us attach extra validation metadata to a plain type (str)
# without creating a whole new class.
from typing import Annotated

# AfterValidator wraps a plain function so pydantic runs it AFTER its own
# normal type validation succeeds (i.e. after confirming the value is a str).
from pydantic import AfterValidator

# A deliberately simple pattern: "something@something.something", no spaces,
# no "@" repeated. Not a full RFC-5322 email grammar — just enough to catch
# obviously malformed input without pulling in a whole library for it.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EMAIL_LENGTH = 254  # RFC 5321 mailbox length limit


def _validate_email_format(value: str) -> str:
    # Trim surrounding whitespace before checking anything else.
    value = value.strip()
    # Reject: empty string, too long, or doesn't match the basic email shape.
    if not value or len(value) > MAX_EMAIL_LENGTH or not _EMAIL_RE.match(value):
        raise ValueError("Invalid email address")
    # Return the (trimmed) value — pydantic stores whatever this returns.
    return value


# Use as the type for any input field that must be a well-formed email address.
# For an optional field, use ``EmailField | None = None`` — pydantic only runs
# the validator on the branch of the union it matches, so ``None`` passes through.
# Annotated[str, AfterValidator(...)] means: "this field is a str, and after
# pydantic confirms that, also run _validate_email_format on it."
EmailField = Annotated[str, AfterValidator(_validate_email_format)]
