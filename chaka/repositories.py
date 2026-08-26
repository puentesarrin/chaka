"""SQL-backed persistence adapters (repositories) over a sessionmaker.

These isolate ORM/query details behind small classes so the manager, handler, and
routers don't embed SQLAlchemy. Each method opens its own short-lived session.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence

from sqlalchemy import func, select, update

from chaka import clock, interfaces, models
from chaka.database import SessionMaker
from chaka.types import Delivery


class VoiceLogRepository(interfaces.IVoiceLog):
    def __init__(self, sessionmaker: SessionMaker) -> None:
        self._sessionmaker = sessionmaker

    async def start(self, *, token_id: int, token_name: str, channel_id: int) -> Optional[int]:
        async with self._sessionmaker() as db:
            entry = models.VoiceLog(
                token_id=token_id,
                token_name=token_name,
                channel_id=channel_id,
                started_at=clock.utcnow(),
                listeners=0,
            )
            db.add(entry)
            await db.commit()
            return entry.id

    async def update(self, log_id: int, *, bytes_relayed: int, listeners: int) -> None:
        async with self._sessionmaker() as db:
            await db.execute(
                update(models.VoiceLog)
                .where(models.VoiceLog.id == log_id)
                .values(bytes_relayed=bytes_relayed, listeners=listeners)
            )
            await db.commit()

    async def end(self, log_id: int, *, bytes_relayed: int) -> None:
        async with self._sessionmaker() as db:
            await db.execute(
                update(models.VoiceLog)
                .where(models.VoiceLog.id == log_id)
                .values(ended_at=clock.utcnow(), bytes_relayed=bytes_relayed)
            )
            await db.commit()


class UserRepository:
    """Admin-UI accounts. Used by the auth layer on every authenticated request,
    so lookups are by primary key or by the unique ``username``."""

    def __init__(self, sessionmaker: SessionMaker) -> None:
        self._sessionmaker = sessionmaker

    async def get(self, user_id: int) -> Optional[models.User]:
        async with self._sessionmaker() as db:
            result = await db.execute(select(models.User).where(models.User.id == user_id))
            return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[models.User]:
        async with self._sessionmaker() as db:
            result = await db.execute(select(models.User).where(models.User.username == username))
            return result.scalar_one_or_none()

    async def count(self) -> int:
        async with self._sessionmaker() as db:
            result = await db.execute(select(func.count()).select_from(models.User))
            return int(result.scalar() or 0)

    async def create(
        self,
        *,
        username: str,
        email: str,
        password_hash: str,
        full_name: Optional[str] = None,
        is_active: bool = True,
    ) -> models.User:
        async with self._sessionmaker() as db:
            user = models.User(
                username=username,
                email=email,
                full_name=full_name,
                password_hash=password_hash,
                is_active=is_active,
                created_at=clock.utcnow(),
            )
            db.add(user)
            await db.commit()
            return user

    async def set_password_hash(self, user_id: int, password_hash: str) -> None:
        async with self._sessionmaker() as db:
            await db.execute(update(models.User).where(models.User.id == user_id).values(password_hash=password_hash))
            await db.commit()

    async def mark_login(self, user_id: int, when: datetime) -> None:
        async with self._sessionmaker() as db:
            await db.execute(update(models.User).where(models.User.id == user_id).values(last_login_at=when))
            await db.commit()


class TokenRepository:
    def __init__(self, sessionmaker: SessionMaker) -> None:
        self._sessionmaker = sessionmaker

    async def get_active(self, token: str) -> Optional[models.Token]:
        async with self._sessionmaker() as db:
            result = await db.execute(
                select(models.Token).where(models.Token.token == token, models.Token.is_active.is_(True))
            )
            return result.scalar_one_or_none()

    async def record_event(self, *, token_id: int, token_name: str, event: str, detail: dict) -> None:
        async with self._sessionmaker() as db:
            db.add(
                models.TokenEvent(
                    token_id=token_id,
                    token_name=token_name,
                    event=event,
                    occurred_at=clock.utcnow(),
                    detail=detail,
                )
            )
            await db.commit()

    async def mark_delivered(self, token_ids: Sequence[int], when: datetime) -> None:
        if not token_ids:
            return
        async with self._sessionmaker() as db:
            await db.execute(update(models.Token).where(models.Token.id.in_(token_ids)).values(last_delivered_at=when))
            await db.commit()


class NotificationRepository:
    def __init__(self, sessionmaker: SessionMaker) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        *,
        token_id: Optional[int],
        msg_id: str,
        source: str,
        received_at: datetime,
        client_ip: str,
        payload: dict,
        forwarded_at: Optional[datetime] = None,
    ) -> int:
        async with self._sessionmaker() as db:
            entry = models.NotificationLog(
                token_id=token_id,
                msg_id=msg_id,
                source=source,
                received_at=received_at,
                forwarded_at=forwarded_at,
                client_ip=client_ip,
                payload=payload,
            )
            db.add(entry)
            await db.commit()
            return entry.id

    async def missed_since(self, when: datetime, limit: int) -> List[models.NotificationLog]:
        async with self._sessionmaker() as db:
            result = await db.execute(
                select(models.NotificationLog)
                .where(models.NotificationLog.received_at > when)
                .order_by(models.NotificationLog.received_at.asc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def record_deliveries(self, notification_id: int, recipients: Sequence[Delivery], when: datetime) -> None:
        if not recipients:
            return
        async with self._sessionmaker() as db:
            for recipient in recipients:
                db.add(
                    models.NotificationDelivery(
                        notification_id=notification_id,
                        token_id=recipient.token_id,
                        token_name=recipient.token_name,
                        sent_at=when,
                    )
                )
            await db.commit()

    async def record_replay(
        self, *, token_id: int, token_name: str, notification_ids: Sequence[int], when: datetime
    ) -> None:
        if not notification_ids:
            return
        async with self._sessionmaker() as db:
            for notification_id in notification_ids:
                db.add(
                    models.NotificationDelivery(
                        notification_id=notification_id,
                        token_id=token_id,
                        token_name=token_name,
                        sent_at=when,
                    )
                )
            await db.commit()


class VoiceChannelRepository:
    def __init__(self, sessionmaker: SessionMaker) -> None:
        self._sessionmaker = sessionmaker

    async def list_enabled(self) -> List[models.VoiceChannel]:
        async with self._sessionmaker() as db:
            result = await db.execute(
                select(models.VoiceChannel)
                .where(models.VoiceChannel.is_enabled.is_(True))
                .order_by(models.VoiceChannel.number)
            )
            return list(result.scalars().all())

    async def get_enabled(self, channel_id: int) -> Optional[models.VoiceChannel]:
        async with self._sessionmaker() as db:
            result = await db.execute(
                select(models.VoiceChannel).where(
                    models.VoiceChannel.id == channel_id, models.VoiceChannel.is_enabled.is_(True)
                )
            )
            return result.scalar_one_or_none()
