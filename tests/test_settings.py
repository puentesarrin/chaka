from chaka import application

_ENV = [
    'TITLE',
    'DATABASE_URL',
    'ADMIN_USER',
    'ADMIN_PASSWORD',
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


def test_settings_is_frozen():
    s = application.Settings()
    try:
        s.title = 'nope'
    except Exception as exc:
        assert exc.__class__.__name__ == 'FrozenInstanceError'
    else:
        raise AssertionError('Settings should be immutable')
