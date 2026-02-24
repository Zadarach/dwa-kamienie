"""
database.py - SQLite z connection pool i WAL dla RPi3b.

Problem który rozwiązuje connection pool:
  Flask (WebPanel), Scraper i Sender działają w osobnych wątkach.
  sqlite3.connect() tworzy nowe połączenie przy każdym wywołaniu — 
  każde połączenie otwiera/zamyka plik → locki → "database is locked".

Rozwiązanie:
  threading.local() — każdy wątek ma WŁASNE połączenie SQLite.
  Jedno połączenie = brak rywalizacji między wątkami.
  WAL + busy_timeout = brak locków nawet przy równoległych zapisach.
"""
import sqlite3
import os
import threading
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "vinted_notification.db")

INIT_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
PRAGMA cache_size=-2000;
PRAGMA temp_store=MEMORY;

CREATE TABLE IF NOT EXISTS config (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS queries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    url                 TEXT NOT NULL UNIQUE,
    discord_webhook_url TEXT NOT NULL,
    channel_name        TEXT NOT NULL DEFAULT 'general',
    embed_color         TEXT NOT NULL DEFAULT '5763719',
    discord_channel_id  TEXT NOT NULL DEFAULT '',
    active              INTEGER NOT NULL DEFAULT 1,
    last_item_ts        INTEGER,
    items_found         INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vinted_id   TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    brand       TEXT,
    price       TEXT,
    currency    TEXT DEFAULT 'PLN',
    size        TEXT,
    status      TEXT,
    photo_url   TEXT,
    item_url    TEXT,
    query_id    INTEGER REFERENCES queries(id) ON DELETE SET NULL,
    sent_at     TEXT NOT NULL DEFAULT (datetime('now')),
    timestamp   INTEGER
);

CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    level       TEXT NOT NULL DEFAULT 'INFO',
    source      TEXT NOT NULL DEFAULT 'system',
    message     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_items_vinted_id ON items(vinted_id);
CREATE INDEX IF NOT EXISTS idx_items_query_id  ON items(query_id);
CREATE INDEX IF NOT EXISTS idx_items_sent_at   ON items(sent_at);
CREATE INDEX IF NOT EXISTS idx_queries_active  ON queries(active);
CREATE INDEX IF NOT EXISTS idx_logs_level      ON logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_created    ON logs(created_at);

INSERT OR IGNORE INTO config (key, value) VALUES
    ('scan_interval',   '60'),
    ('items_per_query', '20'),
    ('new_item_window', '5'),
    ('query_delay',     '5'),
    ('proxy_list',        ''),
    ('proxy_list_url',    ''),
    ('proxy_check_enabled', 'false'),
    ('version',         '2.0.0'),
    ('discord_bot_token', ''),
    ('discord_mode',     'webhook');
"""


# ─────────────────────────────────────────────────────────
# Connection Pool — thread-local connections
# ─────────────────────────────────────────────────────────
class _ConnectionPool:
    """
    Każdy wątek dostaje własne połączenie SQLite.
    
    Dlaczego nie jeden connection dla wszystkich?
      SQLite nie jest thread-safe w trybie shared connection.
      threading.local() gwarantuje że Flask-wątek, Scraper-wątek
      i Sender-wątek nigdy nie używają tego samego obiektu conn.
    
    Dlaczego nie tworzyć nowego conn przy każdym zapytaniu?
      Overhead open/close pliku. Przy 60s interwale i logach to ~100
      operacji/min — każda z nowym połączeniem to marnowanie I/O na RPi.
    """
    def __init__(self):
        self._local = threading.local()

    def get(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            conn = sqlite3.connect(
                DB_PATH,
                timeout=10,           # czekaj max 10s na lock zamiast rzucać wyjątek
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            # WAL + busy_timeout = równoległe odczyty bez locków
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")   # szybsze zapisy, bezpieczne przy WAL
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")    # SQLite czeka 5s na lock
            conn.execute("PRAGMA cache_size=-2000")     # 2MB cache — RPi3B optymalizacja (3×2MB=6MB vs 3×8MB=24MB)
            conn.execute("PRAGMA temp_store=MEMORY")    # temp tables w RAM
            self._local.conn = conn
        return self._local.conn

    def close_current(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


_pool = _ConnectionPool()


@contextmanager
def get_connection():
    """
    Context manager zwracający thread-local connection.
    NIE zamyka połączenia po bloku — jest reużywane przez wątek.
    """
    conn = _pool.get()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    """Inicjalizuje bazę danych — wywołuj raz przy starcie."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _pool.get()
    conn.executescript(INIT_SQL)
    conn.commit()


# ─────────────────────────────────────────────────────────
# CONFIG (z cache dla scrapera — mniej odczytów DB)
# ─────────────────────────────────────────────────────────

_config_cache: dict = {}
_config_cache_ts: float = 0
_CONFIG_TTL: float = 2.0
_config_lock = threading.Lock()


def _invalidate_config_cache():
    """Czyści cache konfiguracji — wymusza ponowny odczyt z DB (SIGHUP reload)."""
    global _config_cache, _config_cache_ts
    with _config_lock:
        _config_cache.clear()
        _config_cache_ts = 0


def get_config(key: str, default: str = None) -> Optional[str]:
    import time
    global _config_cache, _config_cache_ts
    now = time.time()
    with _config_lock:
        if now - _config_cache_ts > _CONFIG_TTL:
            _config_cache.clear()
            _config_cache_ts = now
        if key not in _config_cache:
            with get_connection() as conn:
                row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
                _config_cache[key] = row["value"] if row else default
        return _config_cache[key]


def _invalidate_config_cache():
    """Wywołaj po set_config — wymusza odświeżenie przy następnym get_config."""
    global _config_cache_ts
    with _config_lock:
        _config_cache_ts = 0


def set_config(key: str, value: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO config(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )
    _invalidate_config_cache()


# ─────────────────────────────────────────────────────────
# QUERIES
# ─────────────────────────────────────────────────────────

def get_all_queries(active_only: bool = True) -> List[sqlite3.Row]:
    with get_connection() as conn:
        if active_only:
            return conn.execute(
                "SELECT * FROM queries WHERE active=1 ORDER BY id"
            ).fetchall()
        return conn.execute("SELECT * FROM queries ORDER BY id").fetchall()


def get_query_by_id(query_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM queries WHERE id=?", (query_id,)).fetchone()


def query_exists(url: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM queries WHERE url=?", (url,)
        ).fetchone()
        return row["cnt"] > 0


def add_query(
    name: str,
    url: str,
    discord_webhook_url: str,
    channel_name: str = "general",
    embed_color: str = "5763719",
    discord_channel_id: str = "",
) -> int:
    from src.core import normalize_query_url
    normalized = normalize_query_url(url)
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO queries (name, url, discord_webhook_url, channel_name, embed_color, discord_channel_id)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name, normalized, discord_webhook_url, channel_name, embed_color, discord_channel_id)
        )
        return cur.lastrowid


def update_query(
    query_id: int, name: str, url: str, discord_webhook_url: str,
    channel_name: str, embed_color: str, active: bool,
    discord_channel_id: str = "",
):
    from src.core import normalize_query_url
    normalized = normalize_query_url(url)
    with get_connection() as conn:
        conn.execute(
            "UPDATE queries SET name=?, url=?, discord_webhook_url=?, "
            "channel_name=?, embed_color=?, active=?, discord_channel_id=? WHERE id=?",
            (name, normalized, discord_webhook_url, channel_name,
             embed_color, 1 if active else 0, discord_channel_id, query_id)
        )


def delete_query(query_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM queries WHERE id=?", (query_id,))


def toggle_query(query_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT active FROM queries WHERE id=?", (query_id,)).fetchone()
        if not row:
            return False
        new = 0 if row["active"] else 1
        conn.execute("UPDATE queries SET active=? WHERE id=?", (new, query_id))
        return bool(new)


def update_query_last_ts(query_id: int, timestamp: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE queries SET last_item_ts=? WHERE id=?", (timestamp, query_id)
        )


def increment_query_items_found(query_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE queries SET items_found=items_found+1 WHERE id=?", (query_id,)
        )


def set_all_queries_active(active: bool):
    with get_connection() as conn:
        conn.execute("UPDATE queries SET active=?", (1 if active else 0,))


def get_queries_summary() -> dict:
    with get_connection() as conn:
        total  = conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM queries WHERE active=1").fetchone()[0]
        return {"total": total, "active": active, "inactive": total - active}


# ─────────────────────────────────────────────────────────
# ITEMS
# ─────────────────────────────────────────────────────────

def item_exists(vinted_id: str) -> bool:
    """Szybkie sprawdzenie — EXISTS z LIMIT 1 zamiast COUNT(*)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM items WHERE vinted_id=? LIMIT 1", (str(vinted_id),)
        ).fetchone()
        return row is not None


def add_item(
    vinted_id: str, title: str, brand: str, price: str, currency: str,
    size: str, status: str, photo_url: str, item_url: str,
    query_id: int, timestamp: int
):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO items "
            "(vinted_id,title,brand,price,currency,size,status,photo_url,item_url,query_id,timestamp)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (str(vinted_id), title, brand, str(price), currency,
             size, status, photo_url, item_url, query_id, timestamp)
        )


def get_items(limit: int = 100, query_id: int = None) -> List[sqlite3.Row]:
    with get_connection() as conn:
        if query_id:
            return conn.execute(
                "SELECT i.*, q.name as query_name, q.channel_name "
                "FROM items i LEFT JOIN queries q ON i.query_id=q.id "
                "WHERE i.query_id=? ORDER BY i.sent_at DESC LIMIT ?",
                (query_id, limit)
            ).fetchall()
        return conn.execute(
            "SELECT i.*, q.name as query_name, q.channel_name "
            "FROM items i LEFT JOIN queries q ON i.query_id=q.id "
            "ORDER BY i.sent_at DESC LIMIT ?",
            (limit,)
        ).fetchall()


def get_stats() -> Dict[str, Any]:
    """Jeden zapytanie zamiast 4 — GROUP BY + conditional aggregation."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM items) as total_items,
                (SELECT COUNT(*) FROM queries WHERE active=1) as active_q,
                (SELECT COUNT(*) FROM queries) as total_q,
                (SELECT COUNT(*) FROM items WHERE date(sent_at)=date('now')) as today_items
        """).fetchone()
        return {
            "total_items":    row["total_items"],
            "active_queries": row["active_q"],
            "total_queries":  row["total_q"],
            "today_items":    row["today_items"],
        }


# ─────────────────────────────────────────────────────────
# LOGS
# ─────────────────────────────────────────────────────────

_log_insert_count = 0
_log_insert_lock = threading.Lock()

def add_log(level: str, source: str, message: str):
    global _log_insert_count
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO logs (level,source,message) VALUES (?,?,?)",
                (level.upper(), source, message)
            )
            # Pruning co 100 wpisów zamiast co wpis — 99% mniej DELETE ops (RPi SD wear)
            with _log_insert_lock:
                _log_insert_count += 1
                should_prune = (_log_insert_count % 100 == 0)
            if should_prune:
                conn.execute("""
                    DELETE FROM logs WHERE id < (
                        SELECT id FROM logs ORDER BY id DESC LIMIT 1 OFFSET 1999
                    )
                """)
    except Exception as e:
        print(f"[DB] Log error: {e}")


def get_logs(limit: int = 200, level: str = None) -> List[sqlite3.Row]:
    with get_connection() as conn:
        if level and level != "ALL":
            return conn.execute(
                "SELECT * FROM logs WHERE level=? ORDER BY id DESC LIMIT ?",
                (level.upper(), limit)
            ).fetchall()
        return conn.execute(
            "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


def clear_logs():
    with get_connection() as conn:
        conn.execute("DELETE FROM logs")
