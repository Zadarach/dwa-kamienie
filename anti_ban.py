"""
anti_ban.py - Wielowarstwowa ochrona przed detekcją przez Vinted.

Architektura ochrony:
  Layer 1: Pula 14 User-Agentów (Chrome/Firefox/Edge/Safari × Win/Mac/Linux) — aktualne wersje 2026
  Layer 2: Rotacja nagłówków (Accept-Language, Referer pattern)
  Layer 3: Firefox pomija nagłówki Sec-* (realistyczne zachowanie)
  Layer 4: Rate Limiter token-bucket (max 25 req/min globalnie)
  Layer 5: Rotacja sesji co 80-120 żądań LUB co 90 minut
  Layer 6: Gaussian jitter na każdym delay (ludzki wzorzec)
  Layer 7: Exponential backoff z full-jitter przy błędach
  Layer 8: Losowy Referer przy każdym żądaniu API
  Layer 9: curl_cffi — TLS fingerprint imitujący prawdziwy Chrome (bypass Cloudflare JA3)

WYMAGANIA:
  pip install curl_cffi --break-system-packages
  (jeśli brak curl_cffi — fallback do requests z ostrzeżeniem)
"""

import time
import random
import threading
from collections import deque
from typing import Optional

from src.logger import get_logger
logger = get_logger("anti_ban")

# ─────────────────────────────────────────────────────────
# curl_cffi — preferowany backend (TLS fingerprint Chrome)
# requests   — fallback gdy curl_cffi niedostępny
# ─────────────────────────────────────────────────────────
try:
    from curl_cffi.requests import Session as CurlSession
    import curl_cffi.requests as _curl_requests
    _CURL_AVAILABLE = True
    logger.info("curl_cffi dostępny — używam TLS fingerprint Chrome133")
except ImportError:
    import requests as _fallback_requests
    _CURL_AVAILABLE = False
    logger.warning(
        "curl_cffi niedostępny — używam requests (ryzyko wykrycia przez Cloudflare). "
        "Zainstaluj: pip install curl_cffi --break-system-packages"
    )

import requests  # zawsze importuj dla proxy_get fallback


# ─────────────────────────────────────────────────────────
# User-Agent pool — ZAKTUALIZOWANE do 2026 (Chrome 133, Firefox 135)
# ─────────────────────────────────────────────────────────
_USER_AGENTS = [
    # Chrome 133 / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    # Chrome 133 / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    # Firefox 135 / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    # Firefox 135 / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.7; rv:135.0) Gecko/20100101 Firefox/135.0",
    # Edge 133 / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
    # Safari 18 / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
    # Chrome / Linux (dla RPi — ukrywamy że to Linux)
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    # Firefox / Linux
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:134.0) Gecko/20100101 Firefox/134.0",
]

# Mapowanie UA → wersja Chrome dla curl_cffi impersonate
_CURL_IMPERSONATE_MAP = {
    "133": "chrome133",
    "132": "chrome132",
}
_CURL_IMPERSONATE_DEFAULT = "chrome133"

_ACCEPT_LANGUAGES = [
    "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "pl,en-US;q=0.9,en;q=0.8",
    "pl-PL,pl;q=0.9,en;q=0.8",
    "pl;q=0.9,en-US;q=0.8,en;q=0.7,de;q=0.6",
    "pl-PL,pl;q=0.8,en-US;q=0.5,en;q=0.3",
]


def _get_referers(host: str = "www.vinted.pl") -> list:
    """Referery dla danej domeny Vinted."""
    base = f"https://{host}"
    return [
        f"{base}/catalog",
        f"{base}/",
        f"{base}/catalog?order=newest_first",
        f"{base}/catalog?order=relevance",
        f"{base}/men",
        f"{base}/women",
    ]


def _pick_impersonate(ua: str) -> str:
    """Dobiera profil curl_cffi do User-Agenta (Chrome version matching)."""
    for ver, profile in _CURL_IMPERSONATE_MAP.items():
        if f"Chrome/{ver}" in ua:
            return profile
    return _CURL_IMPERSONATE_DEFAULT


def build_headers(host: str = "www.vinted.pl") -> dict:
    """
    Buduje losowy zestaw nagłówków HTTP imitujący przeglądarkę.
    Firefox nie wysyła Sec-Fetch-*, Chrome wysyła — oba są realistyczne.
    Wersje Chrome/Firefox zaktualizowane do 2026.
    """
    ua = random.choice(_USER_AGENTS)
    is_firefox = "Firefox" in ua
    is_safari  = "Safari" in ua and "Chrome" not in ua

    headers = {
        "User-Agent":      ua,
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": random.choice(_ACCEPT_LANGUAGES),
        "Referer":         random.choice(_get_referers(host)),
        "Origin":          f"https://{host}",
    }

    if not is_firefox and not is_safari:
        # Wyciągnij wersję Chrome z UA, np. "Chrome/133.0.0.0" → "133"
        chrome_ver = "133"
        for part in ua.split():
            if part.startswith("Chrome/"):
                chrome_ver = part.split("/")[1].split(".")[0]
                break

        headers.update({
            "Sec-Fetch-Dest":     "empty",
            "Sec-Fetch-Mode":     "cors",
            "Sec-Fetch-Site":     "same-origin",
            "Sec-Ch-Ua":          f'"Not(A:Brand";v="99", "Google Chrome";v="{chrome_ver}", "Chromium";v="{chrome_ver}"',
            "Sec-Ch-Ua-Mobile":   "?0",
            "Sec-Ch-Ua-Platform": random.choice(['"Windows"', '"macOS"', '"Linux"']),
        })

    return headers


# ─────────────────────────────────────────────────────────
# Rate Limiter — token bucket
# ─────────────────────────────────────────────────────────
class RateLimiter:
    """Nie przekracza MAX_PER_MINUTE żądań w oknie 60 sekund."""

    def __init__(self, max_per_minute: int = 25):
        self.max_per_minute = max_per_minute
        self._timestamps: deque = deque(maxlen=30)  # hard cap — safety net
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            while self._timestamps and self._timestamps[0] < now - 60:
                self._timestamps.popleft()

            if len(self._timestamps) >= self.max_per_minute:
                sleep_for = 60 - (now - self._timestamps[0]) + random.uniform(0.5, 2.5)
                logger.debug(f"Rate limit — czekam {sleep_for:.1f}s")
                time.sleep(sleep_for)

            self._timestamps.append(time.monotonic())


# ─────────────────────────────────────────────────────────
# Timing helpers
# ─────────────────────────────────────────────────────────
def human_delay(base: float, sigma_ratio: float = 0.25) -> float:
    """Gaussian delay — bardziej ludzki niż uniform random."""
    d = random.gauss(base, base * sigma_ratio)
    return max(d, base * 0.2)


def scan_jitter(base_interval: float) -> float:
    """Jitter dla interwału skanowania. base=60 → 45–90s z okazjonalnymi dłuższymi przerwami."""
    base_jitter = random.uniform(-0.25, 0.35) * base_interval
    extra = random.expovariate(1 / 8) if random.random() < 0.15 else 0
    return max(base_interval + base_jitter + extra, 20)


def backoff(attempt: int, base: float = 3.0, cap: float = 90.0) -> float:
    """Full-jitter exponential backoff."""
    ceiling = min(cap, base * (2 ** attempt))
    return random.uniform(base, ceiling)


# ─────────────────────────────────────────────────────────
# Session Manager
# ─────────────────────────────────────────────────────────
class SessionManager:
    """
    Zarządza sesją HTTP z automatyczną rotacją.

    Rotuje sesję co MAX_REQUESTS żądań (80–120) lub co 90 minut.
    Każda nowa sesja ma inny UA, nagłówki i świeże cookies.
    Symuluje "zamknięcie i otwarcie przeglądarki".

    Używa curl_cffi (TLS fingerprint Chrome) jeśli dostępne,
    w przeciwnym razie fallback do requests.
    """

    _MAX_AGE_MINUTES = 90

    def __init__(self, host: str = "www.vinted.pl"):
        self.host          = host
        self._session      = None          # CurlSession lub requests.Session
        self._req_count    = 0
        self._created_at   = 0.0
        self._max_requests = random.randint(80, 120)
        self._lock         = threading.Lock()
        self._rate_limiter = RateLimiter(max_per_minute=25)
        self._impersonate  = _CURL_IMPERSONATE_DEFAULT  # aktualny profil curl_cffi

    def _create_session(self):
        """Tworzy nową sesję HTTP (curl_cffi lub requests) i pobiera cookies."""
        ua = random.choice(_USER_AGENTS)
        headers = build_headers(self.host)
        headers["User-Agent"] = ua  # spójna UA między build_headers a sesją

        if _CURL_AVAILABLE:
            self._impersonate = _pick_impersonate(ua)
            s = CurlSession(impersonate=self._impersonate)
            s.headers.update(headers)
        else:
            s = requests.Session()
            s.headers.update(headers)

        # Pobierz cookies — pełny GET na stronę główną
        try:
            r = s.get(f"https://{self.host}/", timeout=10, allow_redirects=True)
            if r.status_code == 200:
                cookie_count = len(r.cookies) if _CURL_AVAILABLE else len(s.cookies)
                backend = f"curl_cffi/{self._impersonate}" if _CURL_AVAILABLE else "requests"
                logger.info(
                    f"Nowa sesja [{backend}] — {cookie_count} cookies "
                    f"| UA: {ua[:55]}…"
                )
            else:
                logger.warning(f"Cookies: status {r.status_code}")
        except Exception as e:
            logger.warning(f"Cookies error: {e}")

        return s

    def _should_rotate(self) -> bool:
        if self._session is None:
            return True
        age = (time.time() - self._created_at) / 60
        return self._req_count >= self._max_requests or age >= self._MAX_AGE_MINUTES

    def get(self, url: str, params=None, timeout: int = 15):
        """GET z rate limitingiem i automatyczną rotacją sesji."""
        self._rate_limiter.wait()

        with self._lock:
            if self._should_rotate():
                if self._session:
                    logger.info(
                        f"Rotacja sesji "
                        f"(żądań: {self._req_count}, wiek: {(time.time()-self._created_at)/60:.0f}min)"
                    )
                    time.sleep(human_delay(4.0))  # pauza między sesjami

                self._session      = self._create_session()
                self._req_count    = 0
                self._created_at   = time.time()
                self._max_requests = random.randint(80, 120)

            # Losowy Referer przy każdym żądaniu API
            self._session.headers["Referer"] = random.choice(_get_referers(self.host))
            self._req_count += 1

        return self._session.get(url, params=params, timeout=timeout)

    def invalidate(self):
        """Wymuś nową sesję przy następnym żądaniu (po 401/403)."""
        with self._lock:
            self._session = None
            logger.info("Sesja unieważniona — zostanie odtworzona przy następnym żądaniu")


# ── Proxy-aware GET helper ─────────────────────────────────────────────────
# Używany przez core.py zamiast bezpośrednio session.get()

def proxy_get(session_manager: SessionManager, url: str, params=None, timeout: int = 15):
    """
    Wykonuje GET przez proxy (jeśli dostępne) lub direct.
    Automatycznie raportuje sukces/błąd do proxy_manager.
    """
    from src.proxy_manager import proxy_manager

    proxy = proxy_manager.get_proxy()
    start = time.monotonic()

    try:
        if proxy:
            # Pobierz aktualne nagłówki z sesji (jeśli istnieje)
            current_headers = {}
            if session_manager._session is not None:
                current_headers = dict(session_manager._session.headers)

            if _CURL_AVAILABLE:
                # curl_cffi z proxy
                r = _curl_requests.get(
                    url,
                    params=params,
                    timeout=timeout,
                    proxies=proxy,
                    headers=current_headers or build_headers(session_manager.host),
                    impersonate=session_manager._impersonate,
                )
            else:
                r = requests.get(
                    url,
                    params=params,
                    timeout=timeout,
                    proxies=proxy,
                    headers=current_headers or build_headers(session_manager.host),
                )
        else:
            r = session_manager.get(url, params, timeout)

        elapsed = (time.monotonic() - start) * 1000
        if proxy and r.status_code == 200:
            proxy_manager.report_success(proxy, elapsed)
        return r

    except Exception as e:
        if proxy:
            proxy_manager.report_error(proxy)
        raise e
