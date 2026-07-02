"""initial schema

Consolidated baseline: this single migration creates the full Chaka schema
(tokens, notification log + deliveries, token events, voice channels + voice
log), including indexes, server defaults, foreign-key delete rules, and unique
constraints. The default voice channel is seeded separately in 0002.

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_send", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_receive", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_talk", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_hear", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_delivered_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )

    op.create_table(
        "notification_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=True),
        sa.Column("msg_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="device"),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("forwarded_at", sa.DateTime(), nullable=False),
        sa.Column("client_ip", sa.String(length=45), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["token_id"], ["tokens.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("msg_id", name="uq_notification_log_msg_id"),
    )
    op.create_index("ix_notification_log_token_id", "notification_log", ["token_id"])
    op.create_index("ix_notification_log_received_at", "notification_log", ["received_at"])

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("notification_id", sa.BigInteger(), nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=True),
        sa.Column("token_name", sa.String(length=100), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("acked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["notification_id"], ["notification_log.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["token_id"], ["tokens.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_deliveries_notification_id", "notification_deliveries", ["notification_id"])
    op.create_index("ix_notification_deliveries_token_id", "notification_deliveries", ["token_id"])

    op.create_table(
        "token_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=True),
        sa.Column("token_name", sa.String(length=100), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["token_id"], ["tokens.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_token_events_token_id", "token_events", ["token_id"])
    op.create_index("ix_token_events_occurred_at", "token_events", ["occurred_at"])

    op.create_table(
        "voice_channels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
    )

    op.create_table(
        "voice_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=True),
        sa.Column("token_name", sa.String(length=100), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("bytes_relayed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("listeners", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["token_id"], ["tokens.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["channel_id"], ["voice_channels.id"], name="fk_voice_log_channel_id", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_log_token_id", "voice_log", ["token_id"])
    op.create_index("ix_voice_log_started_at", "voice_log", ["started_at"])


def downgrade() -> None:
    op.drop_table("voice_log")
    op.drop_table("voice_channels")
    op.drop_table("token_events")
    op.drop_table("notification_deliveries")
    op.drop_table("notification_log")
    op.drop_table("tokens")
