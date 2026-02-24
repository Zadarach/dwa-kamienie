"""
main.py - Vinted-Notification v4.0
FUNKCJE: Seller tracking + Price drop + Fast scan (5-8s)
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

_metrics = {
    "scrapes_total":    0,
    "items_sent_total":  0,
    "errors_total":      0,
    "uptime_seconds":    0,
}
_start_time = time.time()

def _format_metrics() -> str:
    _metrics["uptime_seconds"] = int(time.time() - _start_time)
    lines = []
    for key, val in _metrics.items():
        prom_name = f"vinted_{key}"
        prom_type = "counter" if key.endswith("_total") else "gauge"
        lines.append(f"# HELP {prom_name} Vinted bot metric: {key}")
        lines.append(f"# TYPE {prom_name} {prom_type}")
        lines.append(f"{prom_name} {val}")
    return "\n".join(lines) + "\n"

def _sd_notify(state: str):
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    try:
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        sock.sendto(state.encode(), addr)
        sock.close()
    except:
        pass

def _setup_sighup():
    if sys.platform == "win32":
        return
    def _on_sighup(signum, frame):
        main_log.info("🔄 SIGHUP — przeładowanie konfiguracji…")
        try:
            db._invalidate_config_cache()
            main_log.info("  ✅ Config cache wyczyszczony")
        except Exception as e:
            main_log.warning(f"  ⚠️ Błąd: {e}")
        main_log.info("✅ Konfiguracja przeładowana")
        db.add_log("INFO", "main", "Konfiguracja przeładowana")
    signal.signal(signal.SIGHUP, _on_sighup)
    main_log.info("📡 SIGHUP handler aktywny (kill -HUP %d)", os.getpid())

async def async_scraper():
    """Async scraper — FUNKCJA 3: Domyślnie 8s zamiast 60s!"""
    from src.core import scrape_all_queries, scrape_tracked_sellers, warmup
    enable_db_logging()
    main_log.info("▶ Scraper uruchomiony (async)")
    warmup()
    while not _stop.is_set():
        try:
            # FUNKCJA 3: Interwał 5-10s dla szybkiego wykrywania
            interval = int(db.get_config("scan_interval", "8"))
            
            await asyncio.to_thread(scrape_all_queries)
            await asyncio.to_thread(scrape_tracked_sellers)  # FUNKCJA 1
            
            _metrics["scrapes_total"] += 1
            _sd_notify("WATCHDOG=1")
        except Exception as e:
            _metrics["errors_total"] += 1
            main_log.error(f"Błąd scrapera: {e}", exc_info=True)
        sleep_for = scan_jitter(interval)
        try:
            await asyncio.wait_for(_stop.wait(), timeout=sleep_for)
            break
        except asyncio.TimeoutError:
            pass
    main_log.info("⏹ Scraper zatrzymany")

async def async_sender():
    """Async sender — konsumuje queue co 0.1s (szybciej!)"""
    from src.core import process_items_queue
    enable_db_logging()
    main_log.info("▶ Sender uruchomiony (async)")
    while not _stop.is_set():
        try:
            await asyncio.to_thread(process_items_queue)
        except Exception as e:
            _metrics["errors_total"] += 1
            main_log.error(f"Błąd sendera: {e}", exc_info=True)
        try:
            await asyncio.wait_for(_stop.wait(), timeout=0.1)
            break
        except asyncio.TimeoutError:
            pass
    main_log.info("⏹ Sender zatrzymany")

def thread_web():
    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    from web_panel.app import run_panel
    run_panel(host="0.0.0.0", port=8080, debug=False)

def thread_health():
    import json
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
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
    main_log.info("📊 Endpoints: /health, /api/stats, /metrics")
    server.serve_forever()

async def async_main():
    main_log.info("=" * 52)
    main_log.info("  Vinted-Notification v4.0 — FAST SCAN MODE")
    main_log.info("=" * 52)
    db.init_db()
    enable_db_logging()
    main_log.info("✅ Baza danych gotowa")
    queries = db.get_all_queries()
    active  = sum(1 for q in queries if q["active"])
    main_log.info(f"📋 Zapytania: {len(queries)} total, {active} aktywnych")
    _setup_sighup()
    _sd_notify("READY=1")
    headless = os.environ.get("HEADLESS", "1") == "1"
    if headless:
        main_log.info("🚀 Tryb HEADLESS — Flask wyłączony (-35MB RAM)")
        web_thread = threading.Thread(target=thread_health, name="Health", daemon=True)
    else:
        web_thread = threading.Thread(target=thread_web, name="WebPanel", daemon=True)
    web_thread.start()
    scraper_task = asyncio.create_task(async_scraper())
    sender_task  = asyncio.create_task(async_sender())
    main_log.info("  ✅ Scraper + Seller tracking uruchomiony")
    main_log.info("  ✅ Sender uruchomiony")
    main_log.info(f"  📡 PID: {os.getpid()}")
    main_log.info("⚠️  UWAGA: Skanowanie co 5-10s — użyj WARP/proxy!")
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
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        main_log.info("👋 Do widzenia!")

if __name__ == "__main__":
    main()
