"""
logger.py - Konfiguracja logowania dla VintedWatch.
Logi trafiają jednocześnie do konsoli i do bazy danych.
"""
import logging
import sys
from typing import Optional


class DatabaseHandler(logging.Handler):
    """Handler który zapisuje logi do bazy danych SQLite."""

    def __init__(self):
        super().__init__()
        self._enabled = False  # Włączany po inicjalizacji DB

    def enable(self):
        self._enabled = True

    def emit(self, record: logging.LogRecord):
        if not self._enabled:
            return
        try:
            import src.database as db
            level_map = {
                "DEBUG": "INFO",
                "INFO": "INFO",
                "WARNING": "WARNING",
                "ERROR": "ERROR",
                "CRITICAL": "ERROR",
            }
            level = level_map.get(record.levelname, "INFO")
            source = record.name.replace("vinted_watch.", "")
            db.add_log(level, source, self.format(record))
        except Exception:
            pass


# Singleton handler referencja
_db_handler: Optional[DatabaseHandler] = None


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Konfiguruje główny logger aplikacji."""
    global _db_handler

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Format
    fmt = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-8s %(name)-20s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Root logger
    root = logging.getLogger("vinted_watch")
    root.setLevel(numeric_level)
    root.handlers.clear()

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(numeric_level)
    root.addHandler(ch)

    # Database (disabled until DB is ready)
    _db_handler = DatabaseHandler()
    _db_handler.setFormatter(fmt)
    root.addHandler(_db_handler)

    return root


def enable_db_logging():
    """Włącza zapis logów do bazy danych (po inicjalizacji DB)."""
    global _db_handler
    if _db_handler:
        _db_handler.enable()


def get_logger(name: str) -> logging.Logger:
    """Zwraca logger dla danego modułu."""
    if not name.startswith("vinted_watch"):
        name = f"vinted_watch.{name}"
    return logging.getLogger(name)
