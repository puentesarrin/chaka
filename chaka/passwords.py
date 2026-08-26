"""Password hashing for admin users.

PBKDF2-HMAC-SHA256 from the standard library — no extra dependency, in keeping
with the rest of the project. A hash is stored as one self-describing string::

    pbkdf2_sha256$600000$<salt-b64>$<derived-key-b64>

so :data:`ITERATIONS` can be raised later without invalidating existing rows:
verification reads the cost from the stored value, and :func:`needs_rehash`
tells you which rows are worth re-hashing on the next successful login.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALGORITHM = 'pbkdf2_sha256'
ITERATIONS = 600_000
SALT_BYTES = 16

# Verified against when no user matches, so a wrong username and a wrong
# password cost the same and the response time doesn't enumerate accounts.
DUMMY_HASH = f'{ALGORITHM}${ITERATIONS}$' + '$'.join(('c2FsdHNhbHRzYWx0c2E=', 'ZGVjb3lkZWNveWRlY295'))

MIN_LENGTH = 8


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
    return f'{ALGORITHM}${iterations}${_b64(salt)}${_b64(derived)}'


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check of ``password`` against a stored hash.

    A malformed or unknown-algorithm hash verifies as False rather than raising,
    so a corrupted row locks that one account out instead of erroring the login.
    """
    parts = encoded.split('$')
    if len(parts) != 4:
        return False
    algorithm, raw_iterations, salt, expected = parts
    if algorithm != ALGORITHM:
        return False
    try:
        iterations = int(raw_iterations)
        salt_bytes = _unb64(salt)
        expected_bytes = _unb64(expected)
    except ValueError:
        return False
    if iterations < 1:
        return False
    derived = hashlib.pbkdf2_hmac('sha256', password.encode(), salt_bytes, iterations, len(expected_bytes))
    return hmac.compare_digest(derived, expected_bytes)


def needs_rehash(encoded: str, *, iterations: int = ITERATIONS) -> bool:
    """True if the hash was made with an older algorithm or a lower cost."""
    parts = encoded.split('$')
    if len(parts) != 4 or parts[0] != ALGORITHM:
        return True
    try:
        return int(parts[1]) < iterations
    except ValueError:
        return True


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode(), validate=True)
