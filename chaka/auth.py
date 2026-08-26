"""Admin authentication: signed-cookie sessions over database-backed users.

**Bootstrap.** While the ``users`` table is empty, ``ADMIN_USER`` /
``ADMIN_PASSWORD`` from the environment still log in — and the first successful
login is persisted as a real user row. That keeps an upgraded deployment
reachable with the credentials it already has; once any user exists, the
environment credentials stop working.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Request, Response, status

from chaka import clock, models, passwords, repositories, sessions

logger = logging.getLogger('chaka')

BOOTSTRAP_EMAIL_DOMAIN = 'chaka.local'


class NotAuthenticated(HTTPException):
    """Raised when a request carries no usable session."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')


async def authenticate(request: Request, username: str, password: str) -> Optional[models.User]:
    """Return the user for these credentials, or ``None``.

    A wrong username costs the same as a wrong password (both run one PBKDF2
    verification), so response time doesn't reveal which accounts exist.
    """
    users: repositories.UserRepository = request.app.state.user_repo
    user = await users.get_by_username(username.strip())

    if user is None:
        passwords.verify_password(password, passwords.DUMMY_HASH)
        return await _bootstrap(request, username, password)

    if not passwords.verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        logger.warning('Login refused: user=%s is inactive', user.username)
        return None

    if passwords.needs_rehash(user.password_hash):
        await users.set_password_hash(user.id, passwords.hash_password(password))
    await users.mark_login(user.id, clock.utcnow())
    return user


async def _bootstrap(request: Request, username: str, password: str) -> Optional[models.User]:
    """Accept the environment credentials while no user exists, and persist them."""
    settings = request.app.state.settings
    users: repositories.UserRepository = request.app.state.user_repo
    if await users.count() > 0:
        return None
    if username.strip() != settings.admin_user or password != settings.admin_password:
        return None

    user = await users.create(
        username=settings.admin_user,
        email=f'{settings.admin_user}@{BOOTSTRAP_EMAIL_DOMAIN}',
        password_hash=passwords.hash_password(password),
        full_name=None,
        is_active=True,
    )
    await users.mark_login(user.id, clock.utcnow())
    logger.warning(
        'Bootstrapped admin user %r from ADMIN_USER/ADMIN_PASSWORD — set a real email and password on the Users tab',
        user.username,
    )
    return user


def issue_session(response: Response, user: models.User, settings) -> None:
    token = sessions.sign({'uid': user.id, 'username': user.username}, settings.secret_key)
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_max_age,
        httponly=True,
        samesite='lax',
        secure=settings.session_cookie_secure,
        path='/',
    )


def clear_session(response: Response, settings) -> None:
    response.delete_cookie(settings.session_cookie, path='/')


async def session_user(request: Request) -> Optional[models.User]:
    settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie)
    if not token:
        return None
    payload = sessions.unsign(token, settings.secret_key, max_age=settings.session_max_age)
    if payload is None:
        return None
    user_id = payload.get('uid')
    if not isinstance(user_id, int):
        return None
    users: repositories.UserRepository = request.app.state.user_repo
    user = await users.get(user_id)
    if user is None or not user.is_active:
        return None
    else:
        return user


async def require_admin(request: Request) -> models.User:
    user = await session_user(request)
    if user is None:
        raise NotAuthenticated()
    else:
        return user
