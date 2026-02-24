"""
main.py - Vinted-Notification v3.0 — punkt wejścia.

Architektura (asyncio + threading):
  Scraper   — async task, pobiera Vinted co ~60s (aiohttp)
  Sender    — async task, wysyła na Discord co 0.2s (aiohttp)
  WebPanel  — Flask :8080 (thread, daemon) [pomijany w trybie HEADLESS=1]

Faza 3 features:
  • asyncio event loop zamiast threading dla scraper/sender
  • SIGHUP config hot-reload (kill -HUP <pid>)
  • systemd SD_NOTIFY watchdog
  • /metrics endpoint (Prometheus format) w trybie HEADLESS
"""
import asyncio
import threading
import signal
import time
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from src.logger import setup_logging, enable_db_logging, get_logger
import src.database as db
from src.anti_ban import scan_jitter

logger    = setup_logging("INFO")
main_log  = get_logger("main")
_stop     = asyncio.Event()

# ── Metryki (Prometheus-compatible) ────────────────────────
_metrics = {
    "scrapes_total":    0,
    "items_found_total": 0,
    "items_sent_total":  0,
    "errors_total":      0,
    "last_scrape_ts":    0,
    "queue_size":        0,
    "uptime_seconds":    0,
}
_start_time = time.time()


def _format_metrics() -> str:
    """Format metryk w Prometheus text exposition format."""
    _metrics["uptime_seconds"] = int(time.time() - _start_time)
    lines = []
    counter_keys = {"scrapes_total", "items_found_total", "items_sent_total", "errors_total"}
    for key, val in _metrics.items():
        prom_name = f"vinted_{key}"
        prom_type = "counter" if key in counter_keys else "gauge"
        lines.append(f"# HELP {prom_name} Vinted bot metric: {key}")
        lines.append(f"# TYPE {prom_name} {prom_type}")
        lines.append(f"{prom_name} {val}")
    return "\n".join(lines) + "\n"


# ── SD_NOTIFY (systemd watchdog) ───────────────────────────

def _sd_notify(state: str):
    """
    Wysyła notyfikację do systemd (SD_NOTIFY).
    Działa tylko na Linuxie z aktywnym socketem.
    """
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    try:
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if addr.startswith("@"):
            addr = "\0" + addr[1:]  # abstract socket
        sock.sendto(state.encode(), addr)
        sock.close()
    except Exception:
        pass


# ── SIGHUP config reload ──────────────────────────────────

def _setup_sighup():
    """
    Rejestruje handler SIGHUP — hot-reload konfiguracji.
    Linux only (Windows nie obsługuje SIGHUP).
    """
    if sys.platform == "win32":
        main_log.debug("SIGHUP niedostępny na Windows")
        return

    def _on_sighup(signum, frame):
        main_log.info("🔄 SIGHUP — przeładowanie konfiguracji…")
        db.add_log("INFO", "main", "SIGHUP — hot-reload konfiguracji")

        # 1. Invalidate config cache (wymusza re-read z DB)
        try:
            db._invalidate_config_cache()
            main_log.info("  ✅ Config cache wyczyszczony")
        except Exception as e:
            main_log.warning(f"  ⚠️ Błąd invalidate config: {e}")

        # 2. Re-read proxy list
        try:
            from src.proxy_manager import proxy_manager
            proxy_manager.invalidate()
            main_log.info("  ✅ Proxy cache invalidated")
        except Exception as e:
            main_log.warning(f"  ⚠️ Błąd reload proxy: {e}")

        # 3. Cleanup stale sessions (wymuś świeże sesje)
        try:
            from src.core import _session_managers, _session_last_used
            hosts = list(_session_managers.keys())
            _session_managers.clear()
            _session_last_used.clear()
            if hosts:
                main_log.info(f"  ✅ Sesje HTTP wyczyszczone ({len(hosts)})")
        except Exception as e:
            main_log.warning(f"  ⚠️ Błąd cleanup sessions: {e}")

        main_log.info("✅ Konfiguracja przeładowana (SIGHUP)")
        db.add_log("INFO", "main", "Konfiguracja przeładowana")

    signal.signal(signal.SIGHUP, _on_sighup)
    main_log.info("📡 SIGHUP handler aktywny (kill -HUP %d)", os.getpid())


# ─────────────────────────────────────────────
# ASYNC TASKS (scraper + sender)
# ─────────────────────────────────────────────

async def async_scraper():
    """Async scraper — pobiera Vinted co ~60s z jitter."""
    from src.core import scrape_all_queries, warmup

    enable_db_logging()
    main_log.info("▶ Scraper uruchomiony (async)")
    db.add_log("INFO", "scraper", "Scraper uruchomiony (async)")

    # Rozgrzewka — inicjalizacja sesji i cookies
    warmup()

    while not _stop.is_set():
        try:
            interval = int(db.get_config("scan_interval", "60"))
            # asyncio.to_thread() — scrape_all_queries używa blocking I/O
            # (requests.get + time.sleep), więc MUSI iść do thread pool
            await asyncio.to_thread(scrape_all_queries)
            _metrics["scrapes_total"] += 1
            _metrics["last_scrape_ts"] = int(time.time())

            # Watchdog ping po każdym udanym skanie
            _sd_notify("WATCHDOG=1")
        except Exception as e:
            _metrics["errors_total"] += 1
            main_log.error(f"Błąd scrapera: {e}", exc_info=True)

        # Jitter ±25% + okazjonalne dłuższe przerwy
        sleep_for = scan_jitter(interval)
        main_log.debug(f"Następny skan za {sleep_for:.0f}s")

        # asyncio.sleep zamiast time.sleep — nie blokuje event loop
        try:
            await asyncio.wait_for(_stop.wait(), timeout=sleep_for)
            break  # stop event was set
        except asyncio.TimeoutError:
            pass  # timeout = czas na kolejny skan

    main_log.info("⏹ Scraper zatrzymany")


async def async_sender():
    """Async sender — konsumuje queue co 0.2s."""
    from src.core import process_items_queue, items_queue

    enable_db_logging()
    main_log.info("▶ Sender uruchomiony (async)")
    db.add_log("INFO", "sender", "Sender Discord uruchomiony (async)")

    while not _stop.is_set():
        try:
            # asyncio.to_thread() — process_items_queue używa blocking I/O
            # (requests.post + time.sleep), więc musi iść do thread pool
            await asyncio.to_thread(process_items_queue)
            _metrics["queue_size"] = items_queue.qsize()
        except Exception as e:
            _metrics["errors_total"] += 1
            main_log.error(f"Błąd sendera: {e}", exc_info=True)

        try:
            await asyncio.wait_for(_stop.wait(), timeout=0.2)
            break
        except asyncio.TimeoutError:
            pass

    main_log.info("⏹ Sender zatrzymany")


# ─────────────────────────────────────────────
# WEB / HEALTH THREADS
# ─────────────────────────────────────────────

def thread_web():
    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    from web_panel.app import run_panel
    run_panel(host="0.0.0.0", port=8080, debug=False)


def thread_health():
    """
    Lekki endpoint /health, /api/stats, /metrics (tryb HEADLESS).
    Używa wbudowanego http.server (~1MB zamiast Flask ~40MB).
    """
    import json
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            elif self.path == "/api/stats":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                stats = db.get_stats()
                self.wfile.write(json.dumps(stats).encode())
            elif self.path == "/metrics":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(_format_metrics().encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    main_log.info("📊 Endpoints: /health, /api/stats, /metrics (tryb HEADLESS)")
    server.serve_forever()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

async def async_main():
    """Główna funkcja async — uruchamia scraper i sender jako tasks."""
    main_log.info("=" * 52)
    main_log.info("  Vinted-Notification v3.0 — uruchamianie")
    main_log.info("=" * 52)

    db.init_db()
    enable_db_logging()
    main_log.info("✅ Baza danych gotowa")
    db.add_log("INFO", "main", "Vinted-Notification v3.0 uruchomiony")

    queries = db.get_all_queries()
    active  = sum(1 for q in queries if q["active"])
    main_log.info(f"📋 Zapytania: {len(queries)} total, {active} aktywnych")
    if not queries:
        main_log.warning("⚠️  Dodaj zapytania przez panel: http://localhost:8080")

    # SIGHUP handler (Linux only)
    _setup_sighup()

    # SD_NOTIFY: gotowy
    _sd_notify("READY=1")

    # Web panel / health endpoint (w osobnym wątku)
    headless = os.environ.get("HEADLESS", "0") == "1"
    if headless:
        main_log.info("🚀 Tryb HEADLESS — Flask wyłączony (-35MB RAM)")
        web_thread = threading.Thread(target=thread_health, name="Health", daemon=True)
    else:
        web_thread = threading.Thread(target=thread_web, name="WebPanel", daemon=True)

    web_thread.start()
    main_log.info(f"  ✅ Wątek {web_thread.name} uruchomiony")

    if not headless:
        main_log.info("📊 Panel webowy: http://localhost:8080")

    # Uruchom async tasks
    scraper_task = asyncio.create_task(async_scraper())
    sender_task  = asyncio.create_task(async_sender())
    main_log.info("  ✅ Scraper (async task) uruchomiony")
    main_log.info("  ✅ Sender (async task) uruchomiony")
    main_log.info(f"  📡 PID: {os.getpid()}")
    main_log.info("Ctrl+C aby zatrzymać\n")

    # Czekaj na stop
    try:
        await asyncio.gather(scraper_task, sender_task)
    except asyncio.CancelledError:
        pass


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(async_main())
    except KeyboardInterrupt:
        main_log.info("\n⏹ Zatrzymywanie…")
        _stop.set()
        _sd_notify("STOPPING=1")
        db.add_log("INFO", "main", "Vinted-Notification zatrzymany")

        # Daj czas na dokończenie task-ów
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()

        main_log.info("👋 Do widzenia!")


if __name__ == "__main__":
    main()
