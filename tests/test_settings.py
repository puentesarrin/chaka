import pytest

from chaka import application

_ENV = [
    'TITLE',
    'DATABASE_URL',
    'ADMIN_USER',
    'ADMIN_PASSWORD',
    'SECRET_KEY',
    'SESSION_COOKIE',
    'SESSION_MAX_AGE',
    'SESSION_COOKIE_SECURE',
    'HEARTBEAT_INTERVAL',
    'HEARTBEAT_URL',
    'SENTRY_TRACES_SAMPLE_RATE',
]


def test_from_env_uses_defaults(monkeypatch):
    for key in _ENV:
        monkeypatch.delenv(key, raising=False)
    s = application.Settings.from_env()
    assert s.title == 'Chaka'
    assert s.admin_user == 'admin'
    assert s.heartbeat_interval == 60
    assert s.heartbeat_url is None
    assert s.secret_key == ''  # the factory fills this in with a random one
    assert s.session_cookie == 'chaka_session'
    assert s.session_max_age == 12 * 60 * 60
    assert s.session_cookie_secure is False


def test_from_env_applies_overrides_and_casts(monkeypatch):
    monkeypatch.setenv('TITLE', 'Acme Relay')
    monkeypatch.setenv('ADMIN_PASSWORD', 'secret')
    monkeypatch.setenv('HEARTBEAT_INTERVAL', '30')
    monkeypatch.setenv('SENTRY_TRACES_SAMPLE_RATE', '0.5')
    s = application.Settings.from_env()
    assert s.title == 'Acme Relay'
    assert s.admin_password == 'secret'
    assert s.heartbeat_interval == 30 and isinstance(s.heartbeat_interval, int)
    assert s.sentry_traces_sample_rate == 0.5


def test_session_settings_from_env(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'sk')
    monkeypatch.setenv('SESSION_COOKIE', 'sid')
    monkeypatch.setenv('SESSION_MAX_AGE', '600')
    monkeypatch.setenv('SESSION_COOKIE_SECURE', 'true')
    s = application.Settings.from_env()
    assert s.secret_key == 'sk'
    assert s.session_cookie == 'sid'
    assert s.session_max_age == 600 and isinstance(s.session_max_age, int)
    assert s.session_cookie_secure is True


@pytest.mark.parametrize(
    'value, expected',
    [
        ('1', True),
        ('true', True),
        ('TRUE', True),
        ('yes', True),
        ('on', True),
        ('0', False),
        ('false', False),
        ('no', False),
        ('', False),
        ('   ', False),
        ('maybe', False),
    ],
)
def test_boolean_env_parsing(monkeypatch, value, expected):
    monkeypatch.setenv('SESSION_COOKIE_SECURE', value)
    assert application.Settings.from_env().session_cookie_secure is expected


def test_settings_is_frozen():
    s = application.Settings()
    try:
        s.title = 'nope'
    except Exception as exc:
        assert exc.__class__.__name__ == 'FrozenInstanceError'
    else:
        raise AssertionError('Settings should be immutable')
