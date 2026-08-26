"""The auth layer: credential checking, the empty-table bootstrap, and what a
session cookie is trusted to say.

The repositories are mocked — these are the rules, not the SQL.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from chaka import application, auth, models, passwords, sessions

SECRET = 'unit-test-secret'


def make_user(**kw):
    defaults = dict(
        id=1,
        username='jorge',
        email='jorge@example.com',
        full_name=None,
        password_hash=passwords.hash_password('hunter2!!', iterations=1),
        is_active=True,
        created_at=datetime.now(UTC),
        last_login_at=None,
    )
    defaults.update(kw)
    return models.User(**defaults)


@pytest.fixture
def request_for():
    def _make(user=None, *, count=0, cookies=None, settings=None):
        repo = AsyncMock()
        repo.get.side_effect = lambda uid: user if user is not None and uid == user.id else None
        repo.get_by_username.side_effect = lambda name: user if user is not None and name == user.username else None
        repo.count.return_value = count
        repo.create.side_effect = lambda **kw: make_user(id=99, **kw)
        settings = settings or application.Settings(secret_key=SECRET, admin_user='admin', admin_password='changeme')
        state = SimpleNamespace(user_repo=repo, settings=settings)
        return SimpleNamespace(app=SimpleNamespace(state=state), cookies=cookies or {}), repo

    return _make


# --- authenticate -------------------------------------------------------------
async def test_correct_credentials_authenticate(request_for):
    user = make_user()
    request, repo = request_for(user, count=1)
    assert await auth.authenticate(request, 'jorge', 'hunter2!!') is user
    repo.mark_login.assert_awaited_once()


async def test_wrong_password_is_refused(request_for):
    request, repo = request_for(make_user(), count=1)
    assert await auth.authenticate(request, 'jorge', 'wrong') is None
    repo.mark_login.assert_not_awaited()


async def test_unknown_username_is_refused(request_for):
    request, _ = request_for(make_user(), count=1)
    assert await auth.authenticate(request, 'nobody', 'hunter2!!') is None


async def test_inactive_user_is_refused(request_for):
    request, repo = request_for(make_user(is_active=False), count=1)
    assert await auth.authenticate(request, 'jorge', 'hunter2!!') is None
    repo.mark_login.assert_not_awaited()


async def test_username_is_trimmed(request_for):
    request, _ = request_for(make_user(), count=1)
    assert await auth.authenticate(request, '  jorge  ', 'hunter2!!') is not None


async def test_weakly_hashed_password_is_upgraded_on_login(request_for):
    user = make_user(password_hash=passwords.hash_password('hunter2!!', iterations=1))
    request, repo = request_for(user, count=1)
    await auth.authenticate(request, 'jorge', 'hunter2!!')
    repo.set_password_hash.assert_awaited_once()
    _, new_hash = repo.set_password_hash.await_args.args
    assert not passwords.needs_rehash(new_hash)


# --- bootstrap ----------------------------------------------------------------
async def test_env_credentials_work_while_no_user_exists(request_for):
    request, repo = request_for(None, count=0)
    user = await auth.authenticate(request, 'admin', 'changeme')
    assert user is not None and user.username == 'admin'
    repo.create.assert_awaited_once()


async def test_bootstrap_persists_the_account(request_for):
    request, repo = request_for(None, count=0)
    await auth.authenticate(request, 'admin', 'changeme')
    created = repo.create.await_args.kwargs
    assert created['username'] == 'admin'
    assert created['is_active'] is True
    assert passwords.verify_password('changeme', created['password_hash'])


async def test_wrong_env_credentials_are_refused(request_for):
    request, repo = request_for(None, count=0)
    assert await auth.authenticate(request, 'admin', 'nope') is None
    repo.create.assert_not_awaited()


async def test_env_credentials_stop_working_once_a_user_exists(request_for):
    request, repo = request_for(make_user(), count=1)
    assert await auth.authenticate(request, 'admin', 'changeme') is None
    repo.create.assert_not_awaited()


# --- session_user -------------------------------------------------------------
def cookie_for(user_id, settings_secret=SECRET, name='chaka_session'):
    return {name: sessions.sign({'uid': user_id, 'username': 'jorge'}, settings_secret)}


async def test_valid_cookie_resolves_to_the_user(request_for):
    user = make_user()
    request, _ = request_for(user, cookies=cookie_for(user.id))
    assert await auth.session_user(request) is user


async def test_no_cookie_is_no_user(request_for):
    request, _ = request_for(make_user())
    assert await auth.session_user(request) is None


async def test_cookie_signed_with_another_secret_is_ignored(request_for):
    user = make_user()
    request, _ = request_for(user, cookies=cookie_for(user.id, 'a-different-secret'))
    assert await auth.session_user(request) is None


async def test_cookie_for_a_deleted_user_is_ignored(request_for):
    request, _ = request_for(make_user(), cookies=cookie_for(4242))
    assert await auth.session_user(request) is None


async def test_cookie_for_a_deactivated_user_is_ignored(request_for):
    user = make_user(is_active=False)
    request, _ = request_for(user, cookies=cookie_for(user.id))
    assert await auth.session_user(request) is None


async def test_cookie_with_a_non_integer_uid_is_ignored(request_for):
    user = make_user()
    request, _ = request_for(user, cookies={'chaka_session': sessions.sign({'uid': 'one'}, SECRET)})
    assert await auth.session_user(request) is None


async def test_require_admin_raises_without_a_session(request_for):
    request, _ = request_for(make_user())
    with pytest.raises(auth.NotAuthenticated):
        await auth.require_admin(request)


async def test_require_admin_returns_the_user(request_for):
    user = make_user()
    request, _ = request_for(user, cookies=cookie_for(user.id))
    assert await auth.require_admin(request) is user
