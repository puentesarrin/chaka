"""Password hashing: round-trip, the stored format, and how it fails."""

import pytest

from chaka import passwords

# Real cost is ~600k iterations; the behaviour under test is identical at 1.
FAST = dict(iterations=1)


def test_hash_verifies_against_its_own_password():
    encoded = passwords.hash_password('correct horse', **FAST)
    assert passwords.verify_password('correct horse', encoded)


def test_wrong_password_does_not_verify():
    encoded = passwords.hash_password('correct horse', **FAST)
    assert not passwords.verify_password('correct horsf', encoded)
    assert not passwords.verify_password('', encoded)


def test_same_password_hashes_differently_each_time():
    first = passwords.hash_password('same', **FAST)
    second = passwords.hash_password('same', **FAST)
    assert first != second
    assert passwords.verify_password('same', first)
    assert passwords.verify_password('same', second)


def test_encoded_format_is_self_describing():
    algorithm, iterations, salt, digest = passwords.hash_password('x', **FAST).split('$')
    assert algorithm == passwords.ALGORITHM
    assert iterations == '1'
    assert salt and digest


def test_unicode_password_round_trips():
    encoded = passwords.hash_password('contraseña ñandú 🔑', **FAST)
    assert passwords.verify_password('contraseña ñandú 🔑', encoded)


@pytest.mark.parametrize(
    'encoded',
    [
        '',
        'not-a-hash',
        'pbkdf2_sha256$1$onlythree',
        'pbkdf2_sha256$notanumber$c2FsdA==$ZGln',
        'pbkdf2_sha256$0$c2FsdA==$ZGln',
        'md5$1$c2FsdA==$ZGln',
        'pbkdf2_sha256$1$!!!notbase64!!!$ZGln',
    ],
)
def test_malformed_hash_fails_closed(encoded):
    assert not passwords.verify_password('anything', encoded)


def test_dummy_hash_is_verifiable_without_matching():
    assert not passwords.verify_password('anything', passwords.DUMMY_HASH)


def test_needs_rehash_tracks_cost_and_algorithm():
    assert passwords.needs_rehash(passwords.hash_password('x', iterations=1000), iterations=2000)
    assert not passwords.needs_rehash(passwords.hash_password('x', iterations=2000), iterations=2000)
    assert passwords.needs_rehash('md5$1$c2FsdA==$ZGln')
    assert passwords.needs_rehash('garbage')
