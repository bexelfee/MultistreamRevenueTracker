from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .events import EventType, Platform, StreamEvent, parse_iso_datetime

SCHEMA_VERSION = 3


@dataclass(frozen=True)
class StoredRevenueEvent:
    id: int
    platform: Platform
    event_type: EventType
    occurred_at: datetime
    source_event_id: str | None
    gifter_user_id: str | None
    gifter_user_name: str | None
    recipient_user_id: str | None
    recipient_user_name: str | None
    amount_micros: int | None
    amount_display: str | None
    currency: str | None
    quantity: int | None
    tier: str | None
    message: str | None
    raw: dict[str, Any]
    created_at: datetime
    is_test: bool = False


class RevenueDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            if conn.execute("SELECT version FROM schema_version").fetchone() is None:
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            conn.execute(
                "CREATE TABLE IF NOT EXISTS revenue_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, event_type TEXT NOT NULL, "
                "occurred_at TEXT NOT NULL, source_event_id TEXT, gifter_user_id TEXT, gifter_user_name TEXT, "
                "recipient_user_id TEXT, recipient_user_name TEXT, amount_micros INTEGER, amount_display TEXT, "
                "currency TEXT, quantity INTEGER, tier TEXT, message TEXT, raw_json TEXT NOT NULL, "
                "created_at TEXT NOT NULL, is_test INTEGER NOT NULL DEFAULT 0)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_revenue_events_platform_source "
                "ON revenue_events (platform, source_event_id) WHERE source_event_id IS NOT NULL"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_revenue_events_occurred_at ON revenue_events (occurred_at)")
            _migrate_schema(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_revenue_events_is_test ON revenue_events (is_test)")

    def add_revenue_event(self, event: StreamEvent) -> int | None:
        if not event.is_revenue:
            raise ValueError(f"refusing to store non-revenue event type: {event.event_type.value}")
        occurred_at = _ensure_utc(event.occurred_at)
        created_at = datetime.now(timezone.utc)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO revenue_events (platform, event_type, occurred_at, source_event_id, "
                "gifter_user_id, gifter_user_name, recipient_user_id, recipient_user_name, amount_micros, "
                "amount_display, currency, quantity, tier, message, raw_json, created_at, is_test) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.platform.value, event.event_type.value, occurred_at.isoformat(), event.source_event_id,
                    event.gifter_user_id, event.gifter_user_name, event.recipient_user_id, event.recipient_user_name,
                    event.amount_micros, event.amount_display, event.currency, event.quantity, event.tier, event.message,
                    json.dumps(event.raw), created_at.isoformat(), 1 if event.is_test else 0,
                ),
            )
            return None if cursor.rowcount == 0 else int(cursor.lastrowid)

    def remove_revenue_event(self, event_id: int) -> bool:
        with self._connect() as conn:
            return conn.execute("DELETE FROM revenue_events WHERE id = ?", (event_id,)).rowcount > 0

    def delete_all_test_events(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM revenue_events WHERE is_test = 1")
            return cursor.rowcount

    def max_event_id(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM revenue_events").fetchone()
            return int(row[0]) if row else 0

    def get_revenue_event(self, event_id: int) -> StoredRevenueEvent | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM revenue_events WHERE id = ?", (event_id,)).fetchone()
            return _row_to_stored_event(row) if row else None

    def update_revenue_event(
        self,
        event_id: int,
        *,
        event_type: EventType,
        raw: dict[str, Any],
    ) -> StoredRevenueEvent | None:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE revenue_events SET event_type = ?, raw_json = ? WHERE id = ?",
                (event_type.value, json.dumps(raw), event_id),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM revenue_events WHERE id = ?", (event_id,)).fetchone()
            return _row_to_stored_event(row) if row else None

    def list_revenue_events(self, from_datetime: datetime, until_datetime: datetime | None = None, *, limit: int | None = None) -> list[StoredRevenueEvent]:
        query = "SELECT * FROM revenue_events WHERE occurred_at >= ?"
        params: list[Any] = [_ensure_utc(from_datetime).isoformat()]
        if until_datetime is not None:
            query += " AND occurred_at < ?"
            params.append(_ensure_utc(until_datetime).isoformat())
        query += " ORDER BY occurred_at ASC, id ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            return [_row_to_stored_event(row) for row in conn.execute(query, params).fetchall()]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        # Wait up to 5s for a lock instead of failing immediately. Avoids
        # transient "database is locked" errors when monitor threads write
        # concurrently with progress reads on slow disks.
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    columns = {col[1] for col in conn.execute("PRAGMA table_info(revenue_events)")}
    if "is_test" not in columns:
        conn.execute("ALTER TABLE revenue_events ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0")
    _migrate_suppressed_resub_rows(conn)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    version = int(row[0]) if row else 1
    if version < SCHEMA_VERSION:
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))


def _migrate_suppressed_resub_rows(conn: sqlite3.Connection) -> None:
    from .revenue_validity import (
        ACTION_INVALIDATED,
        REASON_DUPLICATE_SUB_RESUB,
        SOURCE_AUTO,
        build_auto_invalid_raw,
    )

    rows = conn.execute(
        "SELECT id, raw_json FROM revenue_events WHERE event_type = ?",
        (EventType.TWITCH_RESUBSCRIPTION_SUPPRESSED.value,),
    ).fetchall()
    for row in rows:
        raw = json.loads(row["raw_json"])
        if not raw.get("valid_event_type"):
            raw = build_auto_invalid_raw(
                EventType.TWITCH_RESUBSCRIPTION.value,
                base_raw=raw,
                reason=REASON_DUPLICATE_SUB_RESUB,
            )
        elif not raw.get("status_history"):
            raw["status_history"] = [{
                "action": ACTION_INVALIDATED,
                "source": SOURCE_AUTO,
                "reason": REASON_DUPLICATE_SUB_RESUB,
                "at": datetime.now(timezone.utc).isoformat(),
            }]
        conn.execute(
            "UPDATE revenue_events SET event_type = ?, raw_json = ? WHERE id = ?",
            (EventType.REVENUE_INVALID.value, json.dumps(raw), row["id"]),
        )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _row_to_stored_event(row: sqlite3.Row) -> StoredRevenueEvent:
    is_test = False
    try:
        is_test = bool(row["is_test"])
    except IndexError:
        pass
    return StoredRevenueEvent(
        id=row["id"], platform=Platform(row["platform"]), event_type=EventType(row["event_type"]),
        occurred_at=parse_iso_datetime(row["occurred_at"]), source_event_id=row["source_event_id"],
        gifter_user_id=row["gifter_user_id"], gifter_user_name=row["gifter_user_name"],
        recipient_user_id=row["recipient_user_id"], recipient_user_name=row["recipient_user_name"],
        amount_micros=row["amount_micros"], amount_display=row["amount_display"], currency=row["currency"],
        quantity=row["quantity"], tier=row["tier"], message=row["message"], raw=json.loads(row["raw_json"]),
        created_at=parse_iso_datetime(row["created_at"]), is_test=is_test,
    )
