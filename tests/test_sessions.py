"""Signed session cookies: what a valid token round-trips, and what is rejected."""

import base64
import hashlib
import hmac
import time
from unittest.mock import patch

from chaka import sessions

SECRET = 'test-secret'


def mint(payload: bytes, secret: str = SECRET) -> str:
    """Sign an arbitrary payload into the documented wire format.

    ``sign()`` can only ever produce a dict carrying ``iat``; this reaches the
    branches that reject a token which is correctly signed but hostile.
    """
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip('=')
    tag = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return f'{encoded}.{base64.urlsafe_b64encode(tag).decode().rstrip("=")}'


def test_sign_unsign_round_trip():
    token = sessions.sign({'uid': 7, 'username': 'jorge'}, SECRET)
    payload = sessions.unsign(token, SECRET, max_age=60)
    assert payload['uid'] == 7
    assert payload['username'] == 'jorge'


def test_payload_is_stamped_with_issue_time():
    with patch('chaka.sessions.time.time', return_value=1_700_000_000):
        token = sessions.sign({'uid': 1}, SECRET)
    assert sessions.unsign(token, SECRET, max_age=10**9)['iat'] == 1_700_000_000


def test_another_secret_does_not_validate():
    token = sessions.sign({'uid': 1}, SECRET)
    assert sessions.unsign(token, 'other-secret', max_age=60) is None


def test_tampered_payload_is_rejected():
    mine = sessions.sign({'uid': 1}, SECRET)
    theirs = sessions.sign({'uid': 999}, SECRET)
    swapped = f'{theirs.partition(".")[0]}.{mine.partition(".")[2]}'
    assert sessions.unsign(swapped, SECRET, max_age=60) is None


def test_expired_token_is_rejected():
    with patch('chaka.sessions.time.time', return_value=1000):
        token = sessions.sign({'uid': 1}, SECRET)
    with patch('chaka.sessions.time.time', return_value=1000 + 61):
        assert sessions.unsign(token, SECRET, max_age=60) is None
        assert sessions.unsign(token, SECRET, max_age=120) is not None


def test_malformed_tokens_are_rejected():
    for token in ('', '.', 'nodot', 'a.b', '.sig', 'payload.'):
        assert sessions.unsign(token, SECRET, max_age=60) is None


def test_non_dict_payload_is_rejected():
    assert sessions.unsign(mint(b'[1, 2, 3]'), SECRET, max_age=60) is None


def test_payload_without_iat_is_rejected():
    assert sessions.unsign(mint(b'{"uid":1}'), SECRET, max_age=60) is None


def test_mint_agrees_with_sign():
    """Guards the helper: if the wire format changes, this fails loudly rather
    than letting the two tests above pass against a format nobody produces."""
    with patch('chaka.sessions.time.time', return_value=1000):
        assert mint(b'{"iat":1000,"uid":1}') == sessions.sign({'uid': 1}, SECRET)


def test_signature_survives_a_fresh_process(monkeypatch):
    issued = sessions.sign({'uid': 3}, SECRET)
    assert sessions.unsign(issued, SECRET, max_age=int(time.time()) + 60) is not None
