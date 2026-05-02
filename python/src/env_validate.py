"""Shared validation helpers for security-sensitive inputs.

Used by QR workers to reject control characters in platform credentials
before they are written to ``hermes-home/.env``.
"""

import re

# Matches any single control character: NUL, \r, \n, DEL (0x7F), and all
# chars below 0x20.  Printable Unicode, including CJK characters, is fine.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def validate_env_value(value: str) -> None:
    if _CONTROL_RE.search(value):
        raise ValueError("Credentials must not contain newline or control characters")
