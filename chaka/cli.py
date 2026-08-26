"""Command-line interface for Chaka.

    chaka serve [--host H] [--port P]      run the server
    chaka init  [--path DIR]               scaffold a server into DIR
    chaka db upgrade [--revision REV]      apply database migrations
    chaka db downgrade --revision REV      roll migrations back
    chaka user create|list|passwd          manage admin-UI accounts

`init` copies the bundled ``static/`` and ``templates/`` into the target
directory (so you can customize them), writes a ``.env`` if one is missing, and
applies migrations — the "install the server" step. The library itself is just
``pip install chaka`` + ``import chaka``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import secrets
import shutil
from pathlib import Path
from typing import Optional

from chaka import passwords

PACKAGE_DIR = Path(__file__).resolve().parent

ENV_TEMPLATE = """\
# Chaka configuration. See README / .env.example for the full list of options.
DATABASE_URL=sqlite+aiosqlite:///./chaka.db

# Signs admin session cookies. Keep it secret; changing it signs everyone out.
SECRET_KEY={secret_key}

# Bootstrap credentials: they log in only while no user exists, and the first
# login turns them into a real account. Create the rest on the Users tab.
ADMIN_USER=admin
ADMIN_PASSWORD=changeme

# Use the customizable copies written by `chaka init`.
STATIC_DIR=./static
TEMPLATES_DIR=./templates
"""


def _alembic_config():
    from alembic.config import Config

    cfg = Config()
    # Point Alembic at the migrations bundled inside the installed package.
    cfg.set_main_option('script_location', str(PACKAGE_DIR / 'alembic'))
    return cfg


def db_upgrade(revision: str = 'head') -> None:
    from alembic import command

    command.upgrade(_alembic_config(), revision)


def db_downgrade(revision: str) -> None:
    from alembic import command

    command.downgrade(_alembic_config(), revision)


def serve(host: str, port: int) -> None:
    from chaka import factory

    factory.create_app().run(host=host, port=port)


def init(path: str) -> None:
    target = Path(path).resolve()
    target.mkdir(parents=True, exist_ok=True)

    shutil.copytree(PACKAGE_DIR / 'static', target / 'static', dirs_exist_ok=True)
    shutil.copytree(PACKAGE_DIR / 'templates', target / 'templates', dirs_exist_ok=True)
    print(f'Copied static/ and templates/ into {target}')

    env_path = target / '.env'
    if env_path.exists():
        print(f'Kept existing {env_path}')
    else:
        env_path.write_text(ENV_TEMPLATE.format(secret_key=secrets.token_urlsafe(48)))
        print(f'Wrote {env_path} — edit DATABASE_URL and admin credentials before serving')

    print('Applying migrations...')
    # From the target dir, so a relative sqlite path in .env resolves to the
    # same file `chaka serve` will open there.
    with contextlib.chdir(target):
        db_upgrade('head')
    print('Done. Start the server with:  chaka serve')


def _user_repo():
    """A :class:`UserRepository` bound to a throwaway engine, plus that engine."""
    from chaka import application, database, repositories

    settings = application.Settings.from_env()
    engine = database.make_engine(settings.database_url)
    return repositories.UserRepository(database.make_sessionmaker(engine)), engine


def _prompt_password(password: Optional[str]) -> str:
    value = password or getpass.getpass('Password: ')
    if len(value) < passwords.MIN_LENGTH:
        raise SystemExit(f'Password must be at least {passwords.MIN_LENGTH} characters')
    elif not password and value != getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords do not match')
    else:
        return value


def user_create(username: str, email: str, full_name: Optional[str], password: Optional[str]) -> None:
    value = _prompt_password(password)

    async def _run() -> None:
        users, engine = _user_repo()
        try:
            if await users.get_by_username(username) is not None:
                raise SystemExit(f'User {username!r} already exists')
            await users.create(
                username=username,
                email=email,
                password_hash=passwords.hash_password(value),
                full_name=full_name,
            )
        finally:
            await engine.dispose()
        print(f'Created user {username!r}')

    asyncio.run(_run())


def user_passwd(username: str, password: Optional[str]) -> None:
    value = _prompt_password(password)

    async def _run() -> None:
        users, engine = _user_repo()
        try:
            user = await users.get_by_username(username)
            if user is None:
                raise SystemExit(f'No such user: {username!r}')
            await users.set_password_hash(user.id, passwords.hash_password(value))
        finally:
            await engine.dispose()
        print(f'Password updated for {username!r}')

    asyncio.run(_run())


def user_list() -> None:
    from sqlalchemy import select

    from chaka import application, database, models

    async def _run() -> None:
        engine = database.make_engine(application.Settings.from_env().database_url)
        try:
            async with database.make_sessionmaker(engine)() as db:
                rows = (await db.execute(select(models.User).order_by(models.User.username))).scalars().all()
        finally:
            await engine.dispose()
        if not rows:
            print('No users yet — create one with `chaka user create`.')
            return
        for user in rows:
            status = 'active' if user.is_active else 'inactive'
            last = user.last_login_at.isoformat(timespec='seconds') if user.last_login_at else 'never'
            print(f'{user.username}\t{user.email}\t{status}\tlast login: {last}')

    asyncio.run(_run())


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog='chaka', description='Chaka relay server')
    sub = parser.add_subparsers(dest='command', required=True)

    p_serve = sub.add_parser('serve', help='run the server')
    p_serve.add_argument('--host', default='127.0.0.1')
    p_serve.add_argument('--port', type=int, default=8000)

    p_init = sub.add_parser('init', help='scaffold a server: copy assets, write .env, migrate')
    p_init.add_argument('--path', default='.', help='target directory (default: current)')

    p_user = sub.add_parser('user', help='manage admin-UI accounts')
    user_sub = p_user.add_subparsers(dest='user_command', required=True)
    p_user_create = user_sub.add_parser('create', help='create an admin user')
    p_user_create.add_argument('--username', required=True)
    p_user_create.add_argument('--email', required=True)
    p_user_create.add_argument('--full-name', default=None)
    p_user_create.add_argument('--password', default=None, help='prompted for when omitted')
    user_sub.add_parser('list', help='list admin users')
    p_user_passwd = user_sub.add_parser('passwd', help="change a user's password")
    p_user_passwd.add_argument('--username', required=True)
    p_user_passwd.add_argument('--password', default=None, help='prompted for when omitted')

    p_db = sub.add_parser('db', help='database commands')
    db_sub = p_db.add_subparsers(dest='db_command', required=True)
    p_upgrade = db_sub.add_parser('upgrade', help='apply migrations to head (or --revision)')
    p_upgrade.add_argument('--revision', default='head')
    p_downgrade = db_sub.add_parser('downgrade', help='roll migrations back to --revision')
    p_downgrade.add_argument('--revision', required=True)

    args = parser.parse_args(argv)

    if args.command == 'serve':
        serve(args.host, args.port)
    elif args.command == 'init':
        init(args.path)
    elif args.command == 'db' and args.db_command == 'upgrade':
        db_upgrade(args.revision)
    elif args.command == 'db' and args.db_command == 'downgrade':
        db_downgrade(args.revision)
    elif args.command == 'user':
        if args.user_command == 'create':
            user_create(args.username, args.email, args.full_name, args.password)
        elif args.user_command == 'list':
            user_list()
        elif args.user_command == 'passwd':
            user_passwd(args.username, args.password)


if __name__ == '__main__':
    main()
