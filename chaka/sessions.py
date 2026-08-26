"""Signed session cookies for the admin UI.

A session is a JSON payload plus an HMAC-SHA256 tag over it, both base64url
encoded: ``<payload>.<signature>``. Nothing is stored server-side — the cookie
carries the user id, the username, and the issue time, and the signature is what
makes it unforgeable. Tampering fails the signature; an old cookie fails the
``max_age`` check.

Stdlib only, like :mod:`chaka.passwords`. The signing key is
``Settings.secret_key``: change it and every outstanding session is invalidated.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional


def sign(payload: Dict[str, Any], secret: str) -> str:
    """Serialize and sign ``payload``, stamping it with the current time."""
    body = dict(payload, iat=int(time.time()))
    raw = json.dumps(body, separators=(',', ':'), sort_keys=True).encode()
    encoded = _b64(raw)
    return f'{encoded}.{_b64(_tag(encoded, secret))}'


def unsign(token: str, secret: str, *, max_age: int) -> Optional[Dict[str, Any]]:
    """Return the payload of a valid, unexpired token, else ``None``."""
    encoded, _, signature = token.partition('.')
    if not encoded or not signature:
        return None
    try:
        expected = _tag(encoded, secret)
        if not hmac.compare_digest(_unb64(signature), expected):
            return None
        payload = json.loads(_unb64(encoded))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    issued_at = payload.get('iat')
    if not isinstance(issued_at, int) or issued_at + max_age < int(time.time()):
        return None
    return payload


def _tag(encoded: str, secret: str) -> bytes:
    return hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
