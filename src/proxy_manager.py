"""
proxy_manager.py - Zarządzanie proxy wzorowane na Vinted-Notifications.

Podejście: proste i skuteczne.
  - Użytkownik podaje proxy przez panel (lista IP:PORT lub URL do listy)
  - Proxy losowane przy każdym żądaniu (random.choice)
  - Cache 6h, opcjonalne testowanie przed użyciem
  - Fallback na direct connection jeśli brak proxy

Dlaczego NIE auto-fetch publicznych list:
  - Publiczne listy proxy mają ~20-40% działających w danej chwili
  - Vinted często blokuje datacenter IP z publicznych list
  - Własne proxy (nawet VPN lub jeden dobry serwer) jest o wiele bardziej stabilne
  - Vinted-Notifications działało 2 dni bez bana właśnie dzięki temu podejściu

Jak skonfigurować proxy przez panel → Ustawienia → Proxy:
  Opcja A: Wklej listę proxy oddzielonych średnikiem
    np. 1.2.3.4:8080;5.6.7.8:3128;user:pass@9.10.11.12:8080
  Opcja B: Podaj URL do listy (np. GitHub raw, ProxyScrape)
    np. https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&...
"""

import random
import time
import threading
import requests
import concurrent.futures
from typing import Optional, List
from src.logger import get_logger

logger = get_logger("proxy")

# Proxy są rechecked co 6 godzin (jak w Vinted-Notifications)
RECHECK_INTERVAL = 6 * 60 * 60
MAX_WORKERS      = 10
TEST_URL         = "https://www.vinted.pl/"
TEST_TIMEOUT     = 5  # sekund — krótki, jak w oryginale (2s tam, 5s u nas dla PL)


class ProxyManager:
    """
    Prosty menedżer proxy z cache i opcjonalnym testowaniem.
    Thread-safe singleton.
    """

    def __init__(self):
        self._cache:          Optional[List[str]] = None
        self._cache_init:     bool  = False
        self._single:         Optional[str] = None   # optymalizacja dla 1 proxy
        self._last_check:     float = 0.0
        self._enabled:        bool  = True
        self._lock            = threading.Lock()

    # ── Publiczny interfejs ─────────────────────────────────────────────────

    def get_proxy_dict(self) -> Optional[dict]:
        """
        Zwraca losowe proxy jako dict dla requests lub None (direct connection).
        Wywołuj przed każdym żądaniem HTTP.
        """
        if not self._enabled:
            return None

        proxy_str = self._get_random_proxy()
        if proxy_str is None:
            return None

        return self._to_dict(proxy_str)

    def invalidate(self):
        """Wymuś ponowne wczytanie listy proxy przy następnym wywołaniu."""
        with self._lock:
            self._cache      = None
            self._cache_init = False
            self._single     = None
            self._last_check = 0.0

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        logger.info(f"Proxy {'włączone' if enabled else 'wyłączone (direct connection)'}")

    def get_stats(self) -> dict:
        """Statystyki dla panelu webowego."""
        with self._lock:
            count = len(self._cache) if self._cache else 0
            return {
                "enabled":       self._enabled,
                "total_proxies": count,
                "has_proxy":     count > 0,
                "last_check":    self._last_check,
                "next_check_in": max(0, int(RECHECK_INTERVAL - (time.time() - self._last_check))),
            }

    # ── Logika wewnętrzna ───────────────────────────────────────────────────

    def _get_random_proxy(self) -> Optional[str]:
        """
        Zwraca losowe proxy z cache.
        Przy pierwszym wywołaniu lub po upłynięciu RECHECK_INTERVAL ładuje listę.
        """
        import src.database as db

        now = time.time()

        with self._lock:
            # Sprawdź czy trzeba przeładować (6h minęło)
            if (
                self._cache_init
                and self._last_check > 0
                and now - self._last_check > RECHECK_INTERVAL
            ):
                self._cache_init = False
                self._cache      = None
                self._single     = None

            # Jeśli cache gotowy — zwróć z niego
            if self._cache_init:
                if self._cache is None:
                    return None
                if self._single is not None:
                    return self._single
                return random.choice(self._cache) if self._cache else None

        # Poza lockiem: załaduj proxy (może chwilę potrwać)
        self._load_proxies(db, now)

        with self._lock:
            if self._cache is None:
                return None
            if self._single is not None:
                return self._single
            return random.choice(self._cache) if self._cache else None

    def _load_proxies(self, db, now: float):
        """Pobiera i (opcjonalnie) testuje proxy z konfiguracji."""
        all_proxies: List[str] = []

        # Źródło 1: ręczna lista z panelu (oddzielona średnikami)
        proxy_list_str = db.get_config("proxy_list", "")
        if proxy_list_str.strip():
            entries = [p.strip() for p in proxy_list_str.split(";") if p.strip()]
            all_proxies.extend(entries)

        # Źródło 2: URL do listy proxy
        proxy_list_url = db.get_config("proxy_list_url", "")
        if proxy_list_url.strip():
            fetched = self._fetch_from_url(proxy_list_url.strip())
            all_proxies.extend(fetched)
            logger.info(f"Pobrano {len(fetched)} proxy z URL")

        if not all_proxies:
            logger.debug("Brak skonfigurowanych proxy — używam direct connection")
            with self._lock:
                self._cache      = None
                self._cache_init = True
                self._last_check = now
            return

        # Opcjonalne testowanie
        check_proxies = db.get_config("proxy_check_enabled", "false").lower() == "true"
        if check_proxies and all_proxies:
            logger.info(f"Testuję {len(all_proxies)} proxy (może chwilę potrwać)…")
            working = self._test_proxies_parallel(all_proxies)
            logger.info(f"Działające proxy: {len(working)}/{len(all_proxies)}")
            final = working if working else all_proxies  # fallback na nieprzetestowane
        else:
            final = all_proxies
            logger.info(f"Załadowano {len(final)} proxy (bez testowania)")

        with self._lock:
            self._cache      = final
            self._cache_init = True
            self._last_check = now
            self._single     = final[0] if len(final) == 1 else None

    def _fetch_from_url(self, url: str) -> List[str]:
        """Pobiera listę proxy z URL (format: IP:PORT per linia)."""
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                lines = []
                for line in r.text.strip().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and ":" in line:
                        lines.append(line)
                return lines
        except Exception as e:
            logger.warning(f"Błąd pobierania listy proxy z URL: {e}")
        return []

    def _test_proxies_parallel(self, proxies_list: List[str]) -> List[str]:
        """Testuje listę proxy równolegle, zwraca działające."""
        working = []
        lock    = threading.Lock()

        def test_one(proxy_str):
            if self._test_proxy(proxy_str):
                with lock:
                    working.append(proxy_str)

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(test_one, p): p for p in proxies_list}
            concurrent.futures.wait(futures, timeout=TEST_TIMEOUT * 3)

        return working

    def _test_proxy(self, proxy_str: str) -> bool:
        """Testuje pojedyncze proxy HEAD requestem na vinted.pl."""
        proxy_dict = self._to_dict(proxy_str)
        try:
            r = requests.head(
                TEST_URL,
                proxies=proxy_dict,
                timeout=TEST_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=False,
            )
            return r.status_code in (200, 302, 301)
        except Exception:
            return False

    @staticmethod
    def _to_dict(proxy_str: str) -> dict:
        """Konwertuje 'IP:PORT' lub 'http://IP:PORT' na dict dla requests."""
        if not proxy_str:
            return {}
        if "://" not in proxy_str:
            proxy_str = f"http://{proxy_str}"
        return {"http": proxy_str, "https": proxy_str}


# Globalny singleton
proxy_manager = ProxyManager()
