"""SQL-backed persistence adapters (repositories) over a sessionmaker.

These isolate ORM/query details behind small classes so the manager, handler, and
routers don't embed SQLAlchemy. Each method opens its own short-lived session.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import List, Optional, Sequence

from sqlalchemy import select, update

from chaka import interfaces, models
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
                started_at=datetime.now(UTC),
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
                .values(ended_at=datetime.now(UTC), bytes_relayed=bytes_relayed)
            )
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
                    occurred_at=datetime.now(UTC),
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
