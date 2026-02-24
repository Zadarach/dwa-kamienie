"""
database.py - SQLite database layer.
WERSJA: 3.6 - Wsparcie dla wielu URLi na zapytanie
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
    """Zwraca połączenie z bazą z włączonym WAL mode."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=10000;")
    return conn

def init_db():
    """Inicjalizuje tabele w bazie danych."""
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                discord_webhook_url TEXT NOT NULL,
                discord_channel_name TEXT,
                embed_color TEXT DEFAULT '5763719',
                active INTEGER DEFAULT 1,
                last_item_ts INTEGER DEFAULT 0,
                items_found INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS query_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                last_item_ts INTEGER DEFAULT 0,
                FOREIGN KEY (query_id) REFERENCES queries(id) ON DELETE CASCADE
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS items (
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (query_id) REFERENCES queries(id)
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT,
                source TEXT,
                message TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Migracja: przenieś istniejące URLe do nowej tabeli
        try:
            c.execute("PRAGMA table_info(queries)")
            columns = [col[1] for col in c.fetchall()]
            if 'url' in columns:
                logger.info("Migracja: przenoszenie URLi do tabeli query_urls...")
                c.execute("""
                    INSERT OR IGNORE INTO query_urls (query_id, url)
                    SELECT id, url FROM queries WHERE url IS NOT NULL AND url != ''
                """)
                conn.commit()
                logger.info("✅ Migracja zakończona")
        except Exception as e:
            logger.warning(f"Migracja nie była potrzebna: {e}")
        
        conn.commit()
        conn.close()
        logger.info("✅ Baza danych zainicjalizowana")

def get_all_queries(active_only=False):
    """Pobiera wszystkie zapytania z ich URLami."""
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

def add_query(name, webhook_url, channel_name, embed_color, urls, active=1):
    """Dodaje nowe zapytanie z wieloma URLami."""
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        
        c.execute("""
            INSERT INTO queries (name, discord_webhook_url, discord_channel_name, embed_color, active)
            VALUES (?, ?, ?, ?, ?)
        """, (name, webhook_url, channel_name, embed_color, active))
        
        query_id = c.lastrowid
        
        for url in urls:
            c.execute("""
                INSERT INTO query_urls (query_id, url)
                VALUES (?, ?)
            """, (query_id, url.strip()))
        
        conn.commit()
        conn.close()
        logger.info(f"✅ Dodano zapytanie '{name}' z {len(urls)} URLami")
        return query_id

def update_query(query_id, name, webhook_url, channel_name, embed_color, urls, active):
    """Aktualizuje zapytanie i jego URLe."""
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        
        c.execute("""
            UPDATE queries 
            SET name=?, discord_webhook_url=?, discord_channel_name=?, embed_color=?, active=?
            WHERE id=?
        """, (name, webhook_url, channel_name, embed_color, active, query_id))
        
        c.execute("DELETE FROM query_urls WHERE query_id = ?", (query_id,))
        
        for url in urls:
            if url.strip():
                c.execute("""
                    INSERT INTO query_urls (query_id, url)
                    VALUES (?, ?)
                """, (query_id, url.strip()))
        
        conn.commit()
        conn.close()
        logger.info(f"✅ Zaktualizowano zapytanie {query_id}")

def delete_query(query_id):
    """Usuwa zapytanie i wszystkie jego URLe."""
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM query_urls WHERE query_id = ?", (query_id,))
        c.execute("DELETE FROM queries WHERE id = ?", (query_id,))
        conn.commit()
        conn.close()

def toggle_query(query_id):
    """Przełącza status aktywności zapytania."""
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE queries SET active = NOT active WHERE id = ?", (query_id,))
        conn.commit()
        conn.close()

def update_query_last_ts(query_id, timestamp):
    """Aktualizuje timestamp ostatniego przedmiotu."""
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE queries SET last_item_ts = ? WHERE id = ?", (timestamp, query_id))
        c.execute("UPDATE query_urls SET last_item_ts = ? WHERE query_id = ?", (timestamp, query_id))
        conn.commit()
        conn.close()

def increment_query_items_found(query_id):
    """Zwiększa licznik znalezionych przedmiotów."""
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("UPDATE queries SET items_found = items_found + 1 WHERE id = ?", (query_id,))
        conn.commit()
        conn.close()

def item_exists(vinted_id):
    """Sprawdza czy przedmiot już istnieje w bazie."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM items WHERE vinted_id = ?", (str(vinted_id),))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def add_item(vinted_id, title, brand, price, currency, size, status, photo_url, item_url, query_id, timestamp):
    """Dodaje przedmiot do bazy."""
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute("""
                INSERT INTO items (vinted_id, title, brand, price, currency, size, status, 
                                   photo_url, item_url, query_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (str(vinted_id), title, brand, price, currency, size, status, 
                  photo_url, item_url, query_id, timestamp))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            conn.close()

def get_all_items(limit=100):
    """Pobiera ostatnie przedmioty."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM items ORDER BY timestamp DESC LIMIT ?", (limit,))
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return items

def add_log(level, source, message):
    """Dodaje wpis do logów."""
    with _lock:
        conn = get_connection()
        c = conn.cursor()
        c.execute("INSERT INTO logs (level, source, message) VALUES (?, ?, ?)", 
                  (level, source, message))
        conn.commit()
        conn.close()

def get_all_logs(limit=100):
    """Pobiera ostatnie logi."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?", (limit,))
    logs = [dict(row) for row in c.fetchall()]
    conn.close()
    return logs

def enable_db_logging():
    """Przekierowuje logi do bazy danych."""
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
    """Pobiera wartość konfiguracji z cache."""
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
    """Ustawia wartość konfiguracji."""
    with _lock:
        global _config_cache
        conn = get_connection()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
        _config_cache.pop(key, None)

def _invalidate_config_cache():
    """Czyści cache konfiguracji."""
    global _config_cache, _config_cache_time
    _config_cache = {}
    _config_cache_time = 0

def get_stats():
    """Pobiera statystyki bazy."""
    conn = get_connection()
    c = conn.cursor()
    stats = {
        "queries": c.execute("SELECT COUNT(*) FROM queries").fetchone()[0],
        "active_queries": c.execute("SELECT COUNT(*) FROM queries WHERE active = 1").fetchone()[0],
        "items": c.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        "logs": c.execute("SELECT COUNT(*) FROM logs").fetchone()[0],
    }
    conn.close()
    return stats
