from __future__ import annotations
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / "watches.db"


@dataclass
class Watch:
    id: str
    name: str
    params: dict
    price_max: float | None
    min_stars: int
    interval_seconds: int
    created_at: float
    last_checked_at: float
    baseline_done: bool
    enabled: bool


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS watches (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            params_json TEXT NOT NULL,
            price_max REAL,
            min_stars INTEGER DEFAULT 3,
            interval_seconds INTEGER DEFAULT 600,
            created_at REAL NOT NULL,
            last_checked_at REAL DEFAULT 0,
            baseline_done INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS seen_items (
            watch_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            first_seen_at REAL NOT NULL,
            PRIMARY KEY (watch_id, item_id)
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            watch_id TEXT NOT NULL,
            item_json TEXT NOT NULL,
            deal_score REAL NOT NULL,
            stars INTEGER NOT NULL,
            created_at REAL NOT NULL,
            dismissed INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    return conn


def _row_to_watch(row: sqlite3.Row) -> Watch:
    return Watch(
        id=row["id"],
        name=row["name"],
        params=json.loads(row["params_json"]),
        price_max=row["price_max"],
        min_stars=row["min_stars"],
        interval_seconds=row["interval_seconds"],
        created_at=row["created_at"],
        last_checked_at=row["last_checked_at"],
        baseline_done=bool(row["baseline_done"]),
        enabled=bool(row["enabled"]),
    )


# ---------------------------------------------------------------------------
# Watch CRUD
# ---------------------------------------------------------------------------

def create_watch(
    name: str,
    params: dict,
    price_max: float | None = None,
    min_stars: int = 3,
    interval_seconds: int = 600,
) -> str:
    watch_id = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            "INSERT INTO watches (id, name, params_json, price_max, min_stars, "
            "interval_seconds, created_at) VALUES (?,?,?,?,?,?,?)",
            (watch_id, name, json.dumps(params), price_max, min_stars,
             interval_seconds, time.time()),
        )
    return watch_id


def get_all_watches() -> list[Watch]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watches ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_watch(r) for r in rows]


def get_enabled_watches() -> list[Watch]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watches WHERE enabled = 1"
        ).fetchall()
    return [_row_to_watch(r) for r in rows]


def delete_watch(watch_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))
        conn.execute("DELETE FROM seen_items WHERE watch_id = ?", (watch_id,))
        conn.execute("DELETE FROM notifications WHERE watch_id = ?", (watch_id,))


def toggle_enabled(watch_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT enabled FROM watches WHERE id = ?", (watch_id,)
        ).fetchone()
        if not row:
            return False
        new_state = 0 if row["enabled"] else 1
        conn.execute(
            "UPDATE watches SET enabled = ? WHERE id = ?", (new_state, watch_id)
        )
    return bool(new_state)


def update_last_checked(watch_id: str, ts: float) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE watches SET last_checked_at = ? WHERE id = ?", (ts, watch_id)
        )


def set_baseline_done(watch_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE watches SET baseline_done = 1 WHERE id = ?", (watch_id,)
        )


# ---------------------------------------------------------------------------
# Seen items
# ---------------------------------------------------------------------------

def get_seen_ids(watch_id: str) -> set[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT item_id FROM seen_items WHERE watch_id = ?", (watch_id,)
        ).fetchall()
    return {r["item_id"] for r in rows}


def mark_seen(watch_id: str, item_ids: list[str]) -> None:
    if not item_ids:
        return
    now = time.time()
    with _connect() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO seen_items (watch_id, item_id, first_seen_at) "
            "VALUES (?, ?, ?)",
            [(watch_id, iid, now) for iid in item_ids],
        )


def purge_old_seen_items(older_than_days: int = 30) -> None:
    cutoff = time.time() - older_than_days * 86_400
    with _connect() as conn:
        conn.execute(
            "DELETE FROM seen_items WHERE first_seen_at < ?", (cutoff,)
        )


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def save_notification(watch_id: str, item, deal_score: float, stars: int) -> str:
    notif_id = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            "INSERT INTO notifications (id, watch_id, item_json, deal_score, stars, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (notif_id, watch_id, json.dumps(item.__dict__), deal_score, stars, time.time()),
        )
    return notif_id


def get_notifications(limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT n.*, w.name as watch_name FROM notifications n "
            "LEFT JOIN watches w ON n.watch_id = w.id "
            "ORDER BY n.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["item"] = json.loads(d.pop("item_json"))
        result.append(d)
    return result


def dismiss_notification(notification_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE notifications SET dismissed = 1 WHERE id = ?", (notification_id,)
        )


def get_unread_count() -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE dismissed = 0"
        ).fetchone()
    return row[0] if row else 0
