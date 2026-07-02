"""Application factory.

:class:`ChakaApplicationFactory` assembles a :class:`~chaka.application.ChakaApp`
from :class:`~chaka.application.Settings`, wiring collaborators onto ``app.state``.
Its ``create_app`` returns the finished app (never the factory itself). The
module-level :data:`create_app` is a convenience alias bound to a default
factory instance::

    from chaka.factory import create_app
    app = create_app()                                  # env-driven
    app = create_app(settings=Settings(...))            # explicit config
    app = create_app(manager=..., handler=..., routers=[...])   # inject collaborators

Customize construction by subclassing and overriding a build step
(``get_manager``, ``get_handler``, ``default_routers``, ``_make_logger``, …),
then use ``MyFactory().create_app``. The runtime lifespan is a method of
:class:`~chaka.application.ChakaApp`, which builds and owns its own FastAPI; the
factory just populates ``app.state`` with the collaborators.
"""

from __future__ import annotations

import logging
import logging.handlers
from typing import Any, List, Optional, Tuple

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from chaka import application, database, interfaces, repositories
from chaka.manager import ConnectionManager
from chaka.routers import ack, admin, channels, clients, logs, notify, send, tokens, voice

LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'


class ChakaApplicationFactory:
    """Builds a :class:`ChakaApp`. Stateless: settings/loggers are per-build locals."""

    handler_class: type[interfaces.IWebSocketHandler] = application.WebSocketHandler

    def create_app(
        self,
        settings: Optional[application.Settings] = None,
        *,
        manager: Optional[interfaces.IConnectionManager] = None,
        handler: Optional[interfaces.IWebSocketHandler] = None,
        routers: Optional[List[Tuple[Any, Optional[str]]]] = None,
    ) -> application.ChakaApp:
        settings = settings or application.Settings.from_env()
        self._init_sentry(settings)
        logger = self._make_logger(settings)
        heartbeat_logger = self._make_heartbeat_logger(settings)

        engine = database.make_engine(settings.database_url)
        sessionmaker = database.make_sessionmaker(engine)

        manager = manager or self.get_manager(repositories.VoiceLogRepository(sessionmaker))
        handler = handler or self.get_handler(logger)

        chaka_app = application.ChakaApp(settings, logger, heartbeat_logger)
        app = chaka_app.fastapi

        app.state.settings = settings
        app.state.manager = manager
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker
        app.state.templates = Jinja2Templates(directory=self._template_dirs(settings))
        app.state.handler = handler
        app.state.token_repo = repositories.TokenRepository(sessionmaker)
        app.state.notification_repo = repositories.NotificationRepository(sessionmaker)
        app.state.channel_repo = repositories.VoiceChannelRepository(sessionmaker)

        self._mount_static(app, settings)
        self._register_routers(app, routers if routers is not None else self.default_routers())

        async def websocket_route(websocket: WebSocket, token: str = '', client: str = '', version: str = '') -> None:
            await websocket.app.state.handler.handle(websocket, token=token, client=client, version=version)

        app.add_api_websocket_route(settings.websocket_path, websocket_route)
        return chaka_app

    def get_manager(self, voice_log: interfaces.IVoiceLog) -> interfaces.IConnectionManager:
        return ConnectionManager(voice_log=voice_log)

    def get_handler(self, logger: logging.Logger) -> interfaces.IWebSocketHandler:
        return self.handler_class(logger)

    def default_routers(self) -> List[Tuple[Any, Optional[str]]]:
        """Return ``(router, prefix)`` pairs. Override/extend to add routers."""
        return [
            (admin.router, None),
            (tokens.router, '/api'),
            (clients.router, '/api'),
            (channels.router, '/api'),
            (logs.router, '/api'),
            (send.router, '/api'),
            (notify.router, '/api'),
            (ack.router, '/api'),
            (voice.router, '/api'),
        ]

    def _register_routers(self, app: FastAPI, routers: List[Tuple[Any, Optional[str]]]) -> None:
        for router, prefix in routers:
            if prefix:
                app.include_router(router, prefix=prefix)
            else:
                app.include_router(router)

    def _template_dirs(self, settings: application.Settings) -> List[str]:
        """The app's templates dir first, then Chaka's bundled dir as a fallback,
        so a consumer only overrides the templates it actually customizes."""
        dirs = [settings.templates_dir]
        if application.DEFAULT_TEMPLATES_DIR not in dirs:
            dirs.append(application.DEFAULT_TEMPLATES_DIR)
        return dirs

    def _mount_static(self, app: FastAPI, settings: application.Settings) -> None:
        # Serve the app's static dir, falling back to Chaka's bundled package static
        # (``packages``), so a consumer only overrides the assets it customizes.
        app.mount(
            '/static',
            StaticFiles(directory=settings.static_dir, packages=[('chaka', 'static')]),
            name='static',
        )

    def _init_sentry(self, settings: application.Settings) -> None:
        if settings.sentry_dsn:
            import sentry_sdk

            sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=settings.sentry_traces_sample_rate)

    def _make_logger(self, settings: application.Settings) -> logging.Logger:
        file_handler = self._make_logging_file_handler(settings, log_file=settings.log_file)
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=[file_handler, logging.StreamHandler()])
        return logging.getLogger('chaka')

    def _make_heartbeat_logger(self, settings: application.Settings) -> logging.Logger:
        heartbeat_file_handler = self._make_logging_file_handler(settings, log_file=settings.heartbeat_log_file)
        heartbeat_logger = logging.getLogger('heartbeat')
        heartbeat_logger.setLevel(logging.INFO)
        heartbeat_logger.addHandler(heartbeat_file_handler)
        heartbeat_logger.propagate = False

        httpx_logger = logging.getLogger('httpx')
        httpx_logger.addHandler(heartbeat_file_handler)
        httpx_logger.propagate = False
        return heartbeat_logger

    @staticmethod
    def _make_logging_file_handler(
        settings: application.Settings, log_file: str
    ) -> logging.handlers.RotatingFileHandler:
        handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=settings.log_max_bytes, backupCount=settings.log_backup_count, encoding='utf-8'
        )
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        return handler


create_app = ChakaApplicationFactory().create_app
