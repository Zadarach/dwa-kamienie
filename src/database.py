"""
database.py - SQLite database layer.
WERSJA: 4.0 - Seller tracking + Price drop + Fast scan support
"""
import sqlite3
import os
import threading
import time
from datetime import datetime
from src.logger import get_logger
logger = get_logger("database")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "vinted_notification.db")
_lock = threading.Lock()

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=1000;")
    conn.execute("PRAGMA wal_autocheckpoint=1000;")
    return conn

def init_db():
    """Inicjalizuje tabele w bazie danych."""
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        
        # Tabela queries (bez zmian)
        c.execute("""CREATE TABLE IF NOT EXISTS queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            discord_webhook_url TEXT NOT NULL,
            discord_channel_name TEXT,
            discord_channel_id TEXT,
            embed_color TEXT DEFAULT '5763719',
            active INTEGER DEFAULT 1,
            last_item_ts INTEGER DEFAULT 0,
            items_found INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # Tabela query_urls (wiele URLi na zapytanie)
        c.execute("""CREATE TABLE IF NOT EXISTS query_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            last_item_ts INTEGER DEFAULT 0,
            FOREIGN KEY (query_id) REFERENCES queries(id) ON DELETE CASCADE
        )""")
        
        # Tabela items
        c.execute("""CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vinted_id TEXT UNIQUE NOT NULL,
            title TEXT,
            brand TEXT,
            price TEXT,
            currency TEXT,
            size TEXT,
            status TEXT,
            photo_url TEXT,
            item_url TEXT,
            query_id INTEGER,
            timestamp INTEGER,
            is_hidden INTEGER DEFAULT 0,
            user_id TEXT,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # ── NOWA TABELA: tracked_sellers (Funkcja 1) ────────────────────
        c.execute("""CREATE TABLE IF NOT EXISTS tracked_sellers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            discord_webhook_url TEXT,
            last_check INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # ── NOWA TABELA: price_tracking (Funkcja 2) ─────────────────────
        c.execute("""CREATE TABLE IF NOT EXISTS price_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_hash TEXT UNIQUE NOT NULL,
            vinted_id TEXT,
            title TEXT,
            brand TEXT,
            size TEXT,
            first_price TEXT,
            last_price TEXT,
            lowest_price TEXT,
            currency TEXT,
            item_url TEXT,
            photo_url TEXT,
            user_id TEXT,
            username TEXT,
            price_drops INTEGER DEFAULT 0,
            last_check INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # Tabela logs
        c.execute("""CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT,
            source TEXT,
            message TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # Tabela config
        c.execute("""CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        
        # Migracja: dodaj kolumny do istniejącej tabeli items
        try:
            c.execute("ALTER TABLE items ADD COLUMN user_id TEXT")
            logger.info("✅ Dodano user_id do items")
        except:
            pass
        
        try:
            c.execute("ALTER TABLE items ADD COLUMN username TEXT")
            logger.info("✅ Dodano username do items")
        except:
            pass
        
        # Czyszczenie starych logów (>7 dni)
        try:
            c.execute("DELETE FROM logs WHERE timestamp < datetime('now', '-7 days')")
            conn.commit()
            logger.info("✅ Wyczyszczono stare logi")
        except Exception as e:
            logger.warning(f"Czyszczenie logów nieudane: {e}")
        
        conn.commit()
        conn.close()
        logger.info("✅ Baza danych zainicjalizowana (v4.0)")

# ── QUERIES ──────────────────────────────────────────────────────

def get_all_queries(active_only=False):
    conn = get_connection()
    c = conn.cursor()
    if active_only:
        c.execute("SELECT * FROM queries WHERE active = 1 ORDER BY id")
    else:
        c.execute("SELECT * FROM queries ORDER BY id")
    queries = []
    for row in c.fetchall():
        query = dict(row)
        c.execute("SELECT url, last_item_ts FROM query_urls WHERE query_id = ?", (query['id'],))
        query['urls'] = [{'url': r['url'], 'last_item_ts': r['last_item_ts']} for r in c.fetchall()]
        queries.append(query)
    conn.close()
    return queries

def add_query(name, webhook_url, channel_id, embed_color, urls, active=1):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""INSERT INTO queries (name, discord_webhook_url, discord_channel_id, embed_color, active)
            VALUES (?, ?, ?, ?, ?)""", (name, webhook_url, channel_id, embed_color, active))
        query_id = c.lastrowid
        for url in urls:
            c.execute("INSERT INTO query_urls (query_id, url) VALUES (?, ?)", (query_id, url.strip()))
        conn.commit()
        conn.close()
        return query_id

def update_query(query_id, name, webhook_url, channel_id, embed_color, urls, active):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""UPDATE queries SET name=?, discord_webhook_url=?, discord_channel_id=?, 
            embed_color=?, active=? WHERE id=?""", (name, webhook_url, channel_id, embed_color, active, query_id))
        c.execute("DELETE FROM query_urls WHERE query_id = ?", (query_id,))
        for url in urls:
            if url.strip():
                c.execute("INSERT INTO query_urls (query_id, url) VALUES (?, ?)", (query_id, url.strip()))
        conn.commit()
        conn.close()

def delete_query(query_id):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM query_urls WHERE query_id = ?", (query_id,))
        c.execute("DELETE FROM queries WHERE id = ?", (query_id,))
        conn.commit()
        conn.close()

def toggle_query(query_id):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE queries SET active = NOT active WHERE id = ?", (query_id,))
        conn.commit()
        conn.close()

def update_query_last_ts(query_id, timestamp):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE queries SET last_item_ts = ? WHERE id = ?", (timestamp, query_id))
        c.execute("UPDATE query_urls SET last_item_ts = ? WHERE query_id = ?", (timestamp, query_id))
        conn.commit()
        conn.close()

def increment_query_items_found(query_id):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE queries SET items_found = items_found + 1 WHERE id = ?", (query_id,))
        conn.commit()
        conn.close()

# ── ITEMS ──────────────────────────────────────────────────────

def item_exists(vinted_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM items WHERE vinted_id = ?", (str(vinted_id),))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def add_item(vinted_id, title, brand, price, currency, size, status, photo_url, item_url, query_id, timestamp, user_id=None, username=None):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute("""INSERT INTO items (vinted_id, title, brand, price, currency, size, status, 
                photo_url, item_url, query_id, timestamp, user_id, username) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(vinted_id), title, brand, price, currency, size, status, photo_url, item_url, query_id, timestamp, user_id, username))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()

def get_all_items(limit=100):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM items ORDER BY timestamp DESC LIMIT ?", (limit,))
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return items

# ── TRACKED SELLERS (Funkcja 1) ─────────────────────────────────

def get_tracked_sellers(active_only=True):
    conn = get_connection()
    c = conn.cursor()
    if active_only:
        c.execute("SELECT * FROM tracked_sellers WHERE active = 1 ORDER BY id")
    else:
        c.execute("SELECT * FROM tracked_sellers ORDER BY id")
    sellers = [dict(row) for row in c.fetchall()]
    conn.close()
    return sellers

def add_tracked_seller(user_id, username, webhook_url, active=1):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute("""INSERT INTO tracked_sellers (user_id, username, discord_webhook_url, active)
                VALUES (?, ?, ?, ?)""", (str(user_id), username, webhook_url, active))
            conn.commit()
            logger.info(f"✅ Dodano sprzedawcę do śledzenia: {username} (ID: {user_id})")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"Sprzedawca już istnieje: {user_id}")
            return False
        finally:
            conn.close()

def update_tracked_seller(seller_id, username, webhook_url, active):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""UPDATE tracked_sellers SET username=?, discord_webhook_url=?, active=?
            WHERE id=?""", (username, webhook_url, active, seller_id))
        conn.commit()
        conn.close()

def delete_tracked_seller(seller_id):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM tracked_sellers WHERE id = ?", (seller_id,))
        conn.commit()
        conn.close()

def update_seller_last_check(user_id):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE tracked_sellers SET last_check = ? WHERE user_id = ?", (int(time.time()), str(user_id)))
        conn.commit()
        conn.close()

# ── PRICE TRACKING (Funkcja 2) ──────────────────────────────────

def _generate_item_hash(title, brand, size):
    """Generuje unikalny hash dla przedmiotu (do śledzenia cen)."""
    import hashlib
    key = f"{title.lower()}|{brand.lower() if brand else ''}|{size.lower() if size else ''}"
    return hashlib.md5(key.encode()).hexdigest()[:16]

def check_price_drop(vinted_id, title, brand, price, currency, size, item_url, photo_url, user_id=None, username=None):
    """
    Sprawdza czy cena spadła dla tego przedmiotu.
    Zwraca: (is_new, price_dropped, drop_amount, old_price)
    """
    item_hash = _generate_item_hash(title, brand, size)
    conn = get_connection()
    c = conn.cursor()
    
    try:
        price_float = float(price.replace(',', '.').replace(' ', ''))
    except:
        price_float = 0
    
    # Sprawdź czy przedmiot już istnieje w tracking
    c.execute("SELECT * FROM price_tracking WHERE item_hash = ? AND active = 1", (item_hash,))
    existing = c.fetchone()
    
    if not existing:
        # Nowy przedmiot - dodaj do trackingu
        with _lock:
            c.execute("""INSERT INTO price_tracking 
                (item_hash, vinted_id, title, brand, size, first_price, last_price, lowest_price, 
                 currency, item_url, photo_url, user_id, username, last_check, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (item_hash, str(vinted_id), title, brand, size, str(price_float), str(price_float), 
                 str(price_float), currency, item_url, photo_url, str(user_id) if user_id else None, 
                 username, int(time.time())))
            conn.commit()
        conn.close()
        return (True, False, 0, 0)  # New item, no price drop
    else:
        # Przedmiot istnieje - sprawdź cenę
        old_price = float(existing['last_price'])
        lowest_price = float(existing['lowest_price'])
        
        if price_float > 0 and price_float < old_price:
            # CENA SPADŁA! 🎉
            price_drop = old_price - price_float
            new_lowest = min(price_float, lowest_price)
            
            with _lock:
                c.execute("""UPDATE price_tracking SET 
                    last_price = ?, lowest_price = ?, price_drops = price_drops + 1, 
                    last_check = ?, updated_at = CURRENT_TIMESTAMP, vinted_id = ?,
                    item_url = ?, photo_url = ?
                    WHERE item_hash = ?""",
                    (str(price_float), str(new_lowest), int(time.time()), str(vinted_id),
                     item_url, photo_url, item_hash))
                conn.commit()
            conn.close()
            return (False, True, price_drop, old_price)  # Price dropped!
        else:
            # Aktualizuj ostatnią cenę (nawet jeśli wzrosła)
            with _lock:
                c.execute("""UPDATE price_tracking SET 
                    last_price = ?, last_check = ?, updated_at = CURRENT_TIMESTAMP,
                    vinted_id = ?, item_url = ?, photo_url = ?
                    WHERE item_hash = ?""",
                    (str(price_float), int(time.time()), str(vinted_id), item_url, photo_url, item_hash))
                conn.commit()
            conn.close()
            return (False, False, 0, old_price)  # No change

def get_price_tracking_stats():
    conn = get_connection()
    c = conn.cursor()
    stats = {
        "tracked_items": c.execute("SELECT COUNT(*) FROM price_tracking").fetchone()[0],
        "price_drops_total": c.execute("SELECT SUM(price_drops) FROM price_tracking").fetchone()[0] or 0,
        "active_tracks": c.execute("SELECT COUNT(*) FROM price_tracking WHERE active = 1").fetchone()[0],
    }
    conn.close()
    return stats

def cleanup_old_price_tracking(days=30):
    """Usuń stare tracki cen (>X dni bez aktualizacji)."""
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        cutoff = int(time.time()) - (days * 86400)
        c.execute("DELETE FROM price_tracking WHERE last_check < ?", (cutoff,))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        return deleted

# ── LOGS ──────────────────────────────────────────────────────

def add_log(level, source, message):
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO logs (level, source, message) VALUES (?, ?, ?)", (level, source, message))
        c.execute("DELETE FROM logs WHERE id IN (SELECT id FROM logs ORDER BY timestamp DESC LIMIT -1 OFFSET 1000)")
        conn.commit()
        conn.close()

def get_all_logs(limit=100):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?", (limit,))
    logs = [dict(row) for row in c.fetchall()]
    conn.close()
    return logs

def enable_db_logging():
    import logging
    from src.logger import DBHandler
    db_handler = DBHandler()
    db_handler.setLevel(logging.INFO)
    logger_module = logging.getLogger()
    logger_module.addHandler(db_handler)

_config_cache = {}
_config_cache_time = 0
_CONFIG_CACHE_TTL = 10

def get_config(key, default=""):
    global _config_cache, _config_cache_time
    now = time.time()
    if now - _config_cache_time > _CONFIG_CACHE_TTL:
        _config_cache = {}
        _config_cache_time = now
    if key not in _config_cache:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        _config_cache[key] = row[0] if row else default
    return _config_cache[key]

def set_config(key, value):
    with _lock:
        global _config_cache
        conn = get_connection()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
        _config_cache.pop(key, None)

def _invalidate_config_cache():
    global _config_cache, _config_cache_time
    _config_cache = {}
    _config_cache_time = 0

def get_stats():
    conn = get_connection()
    c = conn.cursor()
    stats = {
        "queries": c.execute("SELECT COUNT(*) FROM queries").fetchone()[0],
        "active_queries": c.execute("SELECT COUNT(*) FROM queries WHERE active = 1").fetchone()[0],
        "items": c.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        "logs": c.execute("SELECT COUNT(*) FROM logs").fetchone()[0],
        "tracked_sellers": c.execute("SELECT COUNT(*) FROM tracked_sellers WHERE active = 1").fetchone()[0],
        "price_tracks": c.execute("SELECT COUNT(*) FROM price_tracking WHERE active = 1").fetchone()[0],
    }
    conn.close()
    return stats
