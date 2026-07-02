"""seed default voice channel

Inserts a single enabled voice channel ("Channel 1") so the server is usable
out of the box. Kept separate from the schema migration (0001) so the schema
and the seed data read clearly and independently.

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-01 00:00:01.000000
"""
from __future__ import annotations

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    voice_channels_table = sa.table(
        "voice_channels",
        sa.column("number", sa.Integer),
        sa.column("name", sa.String),
        sa.column("is_enabled", sa.Boolean),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(voice_channels_table, [
        {"number": 1, "name": "Channel 1", "is_enabled": True, "created_at": datetime.now(UTC)},
    ])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM voice_channels WHERE number = 1"))
