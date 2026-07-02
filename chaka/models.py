from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase): ...


class Token(Base):
    __tablename__ = 'tokens'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_send: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_receive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_talk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_hear: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    logs: Mapped[List['NotificationLog']] = relationship('NotificationLog', back_populates='token_rel')
    events: Mapped[List['TokenEvent']] = relationship(
        'TokenEvent', back_populates='token_rel', order_by='TokenEvent.occurred_at.desc()'
    )


class NotificationLog(Base):
    __tablename__ = 'notification_log'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey('tokens.id'), nullable=True, index=True)
    msg_id: Mapped[Optional[str]] = mapped_column(String(36), unique=True, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default='device')
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    forwarded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    client_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    token_rel: Mapped[Optional['Token']] = relationship('Token', back_populates='logs')
    deliveries: Mapped[List['NotificationDelivery']] = relationship(
        'NotificationDelivery', back_populates='notification_rel'
    )


class NotificationDelivery(Base):
    __tablename__ = 'notification_deliveries'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey('notification_log.id', ondelete='CASCADE'), nullable=False, index=True
    )
    token_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey('tokens.id', ondelete='SET NULL'), nullable=True, index=True
    )
    token_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    acked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    notification_rel: Mapped['NotificationLog'] = relationship('NotificationLog', back_populates='deliveries')


class TokenEvent(Base):
    __tablename__ = 'token_events'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey('tokens.id', ondelete='SET NULL'), nullable=True, index=True
    )
    token_name: Mapped[str] = mapped_column(String(100), nullable=False)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    detail: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    token_rel: Mapped[Optional['Token']] = relationship('Token', back_populates='events')


class VoiceChannel(Base):
    __tablename__ = 'voice_channels'
    __table_args__ = (UniqueConstraint('number'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    voice_logs: Mapped[List['VoiceLog']] = relationship('VoiceLog', back_populates='channel_rel')


class VoiceLog(Base):
    __tablename__ = 'voice_log'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey('tokens.id', ondelete='SET NULL'), nullable=True, index=True
    )
    token_name: Mapped[str] = mapped_column(String(100), nullable=False)
    channel_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey('voice_channels.id', ondelete='SET NULL'), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    bytes_relayed: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    listeners: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    channel_rel: Mapped[Optional['VoiceChannel']] = relationship('VoiceChannel', back_populates='voice_logs')
