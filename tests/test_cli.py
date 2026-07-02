from unittest.mock import patch

import pytest

from chaka import cli


def test_serve_builds_and_runs_app():
    with patch('chaka.factory.create_app') as create:
        cli.serve('0.0.0.0', 9000)
    create.assert_called_once()
    create.return_value.run.assert_called_once_with(host='0.0.0.0', port=9000)


def test_db_upgrade_invokes_alembic():
    with patch('alembic.command.upgrade') as upgrade:
        cli.db_upgrade('abc')
    assert upgrade.call_count == 1
    assert upgrade.call_args.args[1] == 'abc'


def test_main_dispatches_serve():
    with patch('chaka.cli.serve') as serve:
        cli.main(['serve', '--host', '1.2.3.4', '--port', '7000'])
    serve.assert_called_once_with('1.2.3.4', 7000)


def test_main_dispatches_db_upgrade():
    with patch('chaka.cli.db_upgrade') as upgrade:
        cli.main(['db', 'upgrade', '--revision', 'r1'])
    upgrade.assert_called_once_with('r1')


def test_main_requires_a_command():
    with pytest.raises(SystemExit):
        cli.main([])


def test_init_scaffolds_assets_and_env(tmp_path):
    with patch('chaka.cli.db_upgrade') as upgrade:
        cli.init(str(tmp_path))
    assert (tmp_path / 'static').is_dir()
    assert (tmp_path / 'templates').is_dir()
    assert 'DATABASE_URL' in (tmp_path / '.env').read_text()
    upgrade.assert_called_once_with('head')


def test_init_keeps_existing_env(tmp_path):
    (tmp_path / '.env').write_text('EXISTING=1')
    with patch('chaka.cli.db_upgrade'):
        cli.init(str(tmp_path))
    assert (tmp_path / '.env').read_text() == 'EXISTING=1'
