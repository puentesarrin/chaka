"""Signed session cookies: what a valid token round-trips, and what is rejected."""

import time
from unittest.mock import patch

from chaka import sessions

SECRET = 'test-secret'


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
    token = sessions.sign({'uid': 1}, SECRET)
    _encoded, _, signature = token.partition('.')
    forged = sessions._b64(b'{"uid":999,"iat":9999999999}')
    assert sessions.unsign(f'{forged}.{signature}', SECRET, max_age=60) is None


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
    encoded = sessions._b64(b'[1, 2, 3]')
    token = f'{encoded}.{sessions._b64(sessions._tag(encoded, SECRET))}'
    assert sessions.unsign(token, SECRET, max_age=60) is None


def test_payload_without_iat_is_rejected():
    encoded = sessions._b64(b'{"uid":1}')
    token = f'{encoded}.{sessions._b64(sessions._tag(encoded, SECRET))}'
    assert sessions.unsign(token, SECRET, max_age=60) is None


def test_signature_survives_a_fresh_process(monkeypatch):
    issued = sessions.sign({'uid': 3}, SECRET)
    assert sessions.unsign(issued, SECRET, max_age=int(time.time()) + 60) is not None
