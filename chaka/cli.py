"""Command-line interface for Chaka.

    chaka serve [--host H] [--port P]      run the server
    chaka init  [--path DIR]               scaffold a server into DIR
    chaka db upgrade [--revision REV]      apply database migrations

`init` copies the bundled ``static/`` and ``templates/`` into the target
directory (so you can customize them), writes a ``.env`` if one is missing, and
applies migrations — the "install the server" step. The library itself is just
``pip install chaka`` + ``import chaka``.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

ENV_TEMPLATE = """\
# Chaka configuration. See README / .env.example for the full list of options.
DATABASE_URL=mysql+aiomysql://user:pass@localhost:3306/chaka
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
        env_path.write_text(ENV_TEMPLATE)
        print(f'Wrote {env_path} — edit DATABASE_URL and admin credentials before serving')

    print('Applying migrations...')
    db_upgrade('head')
    print('Done. Start the server with:  chaka serve')


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog='chaka', description='Chaka relay server')
    sub = parser.add_subparsers(dest='command', required=True)

    p_serve = sub.add_parser('serve', help='run the server')
    p_serve.add_argument('--host', default='127.0.0.1')
    p_serve.add_argument('--port', type=int, default=8000)

    p_init = sub.add_parser('init', help='scaffold a server: copy assets, write .env, migrate')
    p_init.add_argument('--path', default='.', help='target directory (default: current)')

    p_db = sub.add_parser('db', help='database commands')
    db_sub = p_db.add_subparsers(dest='db_command', required=True)
    p_upgrade = db_sub.add_parser('upgrade', help='apply migrations to head (or --revision)')
    p_upgrade.add_argument('--revision', default='head')

    args = parser.parse_args(argv)

    if args.command == 'serve':
        serve(args.host, args.port)
    elif args.command == 'init':
        init(args.path)
    elif args.command == 'db' and args.db_command == 'upgrade':
        db_upgrade(args.revision)


if __name__ == '__main__':
    main()
