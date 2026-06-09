from __future__ import annotations
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "auction_watches.db"


@dataclass
class AuctionWatch:
    id: str
    name: str
    params: dict
    price_max: float | None
    interval_seconds: int
    snipe_interval_seconds: int
    ending_window_hours: int
    alert_new_listing: bool
    alert_ending_soon: bool
    created_at: float
    last_checked_at: float
    baseline_done: bool
    enabled: bool


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS auction_watches (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            params_json TEXT NOT NULL,
            price_max REAL,
            interval_seconds INTEGER DEFAULT 1800,
            snipe_interval_seconds INTEGER DEFAULT 300,
            ending_window_hours INTEGER DEFAULT 12,
            alert_new_listing INTEGER DEFAULT 1,
            alert_ending_soon INTEGER DEFAULT 1,
            created_at REAL NOT NULL,
            last_checked_at REAL DEFAULT 0,
            baseline_done INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS auction_seen_items (
            watch_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            end_date TEXT,
            first_seen_at REAL NOT NULL,
            ending_soon_alerted INTEGER DEFAULT 0,
            PRIMARY KEY (watch_id, item_id)
        );
    """)
    conn.commit()
    return conn


def _row_to_watch(row: sqlite3.Row) -> AuctionWatch:
    return AuctionWatch(
        id=row["id"],
        name=row["name"],
        params=json.loads(row["params_json"]),
        price_max=row["price_max"],
        interval_seconds=row["interval_seconds"],
        snipe_interval_seconds=row["snipe_interval_seconds"],
        ending_window_hours=row["ending_window_hours"],
        alert_new_listing=bool(row["alert_new_listing"]),
        alert_ending_soon=bool(row["alert_ending_soon"]),
        created_at=row["created_at"],
        last_checked_at=row["last_checked_at"],
        baseline_done=bool(row["baseline_done"]),
        enabled=bool(row["enabled"]),
    )


# ---------------------------------------------------------------------------
# Watch CRUD
# ---------------------------------------------------------------------------

def create_auction_watch(
    name: str,
    params: dict,
    price_max: float | None = None,
    interval_seconds: int = 1800,
    snipe_interval_seconds: int = 300,
    ending_window_hours: int = 12,
    alert_new_listing: bool = True,
    alert_ending_soon: bool = True,
) -> str:
    watch_id = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            "INSERT INTO auction_watches (id, name, params_json, price_max, "
            "interval_seconds, snipe_interval_seconds, ending_window_hours, "
            "alert_new_listing, alert_ending_soon, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                watch_id, name, json.dumps(params), price_max,
                interval_seconds, snipe_interval_seconds, ending_window_hours,
                int(alert_new_listing), int(alert_ending_soon), time.time(),
            ),
        )
    return watch_id


def get_all_auction_watches() -> list[AuctionWatch]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM auction_watches ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_watch(r) for r in rows]


def get_enabled_auction_watches() -> list[AuctionWatch]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM auction_watches WHERE enabled = 1"
        ).fetchall()
    return [_row_to_watch(r) for r in rows]


def delete_auction_watch(watch_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM auction_watches WHERE id = ?", (watch_id,))
        conn.execute("DELETE FROM auction_seen_items WHERE watch_id = ?", (watch_id,))


def toggle_enabled(watch_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT enabled FROM auction_watches WHERE id = ?", (watch_id,)
        ).fetchone()
        if not row:
            return False
        new_state = 0 if row["enabled"] else 1
        conn.execute(
            "UPDATE auction_watches SET enabled = ? WHERE id = ?", (new_state, watch_id)
        )
    return bool(new_state)


def update_last_checked(watch_id: str, ts: float) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE auction_watches SET last_checked_at = ? WHERE id = ?", (ts, watch_id)
        )


def set_baseline_done(watch_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE auction_watches SET baseline_done = 1 WHERE id = ?", (watch_id,)
        )


# ---------------------------------------------------------------------------
# Seen items
# ---------------------------------------------------------------------------

def get_seen_ids(watch_id: str) -> set[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT item_id FROM auction_seen_items WHERE watch_id = ?", (watch_id,)
        ).fetchall()
    return {r["item_id"] for r in rows}


def get_seen_with_end_dates(watch_id: str) -> dict[str, str | None]:
    """Returns {item_id: end_date} for all seen items for this watch."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT item_id, end_date FROM auction_seen_items WHERE watch_id = ?",
            (watch_id,),
        ).fetchall()
    return {r["item_id"]: r["end_date"] for r in rows}


def mark_seen(watch_id: str, items: list) -> None:
    """Upsert items as seen, storing end_date for ending-soon detection."""
    if not items:
        return
    now = time.time()
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO auction_seen_items (watch_id, item_id, end_date, first_seen_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(watch_id, item_id) DO UPDATE SET end_date = excluded.end_date",
            [(watch_id, item.itemId, item.itemEndDate, now) for item in items],
        )


def mark_ending_soon_alerted(watch_id: str, item_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE auction_seen_items SET ending_soon_alerted = 1 "
            "WHERE watch_id = ? AND item_id = ?",
            (watch_id, item_id),
        )


def get_ending_soon_alerted_ids(watch_id: str) -> set[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT item_id FROM auction_seen_items "
            "WHERE watch_id = ? AND ending_soon_alerted = 1",
            (watch_id,),
        ).fetchall()
    return {r["item_id"] for r in rows}
