"""The one place that decides what "now" means for storage.

Every ``DateTime`` column in :mod:`chaka.models` is naive (no
``timezone=True``), so every value written to one must be naive UTC too —
MySQL accepted a timezone-aware value silently (it has no concept of a
stored offset), but PostgreSQL's ``asyncpg`` driver rejects one outright
against a ``TIMESTAMP WITHOUT TIME ZONE`` column. Call this instead of
``datetime.now(UTC)`` anywhere the result is written to the database.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
