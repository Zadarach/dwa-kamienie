"""
anti_ban.py - Ochrona przed wykryciem i blokadą Vinted.
WERSJA: 4.1 - Bezpieczne minimum 8s zamiast 20s
"""
import random
import time
from src.logger import get_logger
logger = get_logger("anti_ban")

# ── USER AGENT POOL ────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

# ── RATE LIMITER PER-DOMAIN (OPTYMALIZACJA) ───────────────────────
rate_limit_tracker = {
    "pl": {"requests": 0, "reset_time": 0, "last_request": 0},
    "de": {"requests": 0, "reset_time": 0, "last_request": 0},
    "fr": {"requests": 0, "reset_time": 0, "last_request": 0},
    "it": {"requests": 0, "reset_time": 0, "last_request": 0},
    "es": {"requests": 0, "reset_time": 0, "last_request": 0},
    "nl": {"requests": 0, "reset_time": 0, "last_request": 0},
}

RATE_LIMIT_MAX = 50  # Max requestów na minutę na domenę
RATE_LIMIT_WINDOW = 60  # Sekundy

def check_rate_limit(domain: str) -> bool:
    """Sprawdza czy można wykonać request dla danej domeny."""
    now = time.time()
    tracker = rate_limit_tracker.get(domain, {"requests": 0, "reset_time": 0, "last_request": 0})
    
    if now > tracker["reset_time"]:
        tracker["requests"] = 0
        tracker["reset_time"] = now + RATE_LIMIT_WINDOW
    
    if tracker["requests"] >= RATE_LIMIT_MAX:
        wait_time = tracker["reset_time"] - now
        logger.warning(f"Rate limit {domain} — czekam {wait_time:.0f}s")
        return False
    
    tracker["requests"] += 1
    tracker["last_request"] = now
    rate_limit_tracker[domain] = tracker
    return True

def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)

def build_headers(host: str = "www.vinted.pl") -> dict:
    return {
        "User-Agent": get_random_user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Referer": f"https://{host}/",
        "Origin": f"https://{host}",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "TE": "trailers",
    }

def scan_jitter(interval: int) -> float:
    """
    Dodaje losowy jitter do interwału skanowania.
    OPTYMALIZACJA v4.1: Bezpieczne minimum 8s zamiast 20s
    """
    jitter = random.uniform(-3, 3)
    result = max(8, interval + jitter)
    logger.debug(f"Scan jitter: interval={interval}, jitter={jitter:.1f}, result={result:.1f}s")
    return result

def human_delay(min_ms: int = 200, max_ms: int = 800) -> None:
    """Losowe opóźnienie imitujące człowieka."""
    delay = random.uniform(min_ms, max_ms) / 1000.0
    time.sleep(delay)

def backoff(attempt: int, base: float = 2.0, max_wait: float = 30.0) -> float:
    """Exponential backoff dla retry."""
    wait = min(base ** attempt + random.uniform(0, 1), max_wait)
    logger.debug(f"Backoff attempt {attempt}: {wait:.1f}s")
    return wait

class SessionManager:
    """Zarządza sesjami HTTP z rotacją i rate limitingiem."""
    
    def __init__(self, host: str = "www.vinted.pl"):
        self.host = host
        self.domain = host.split(".")[-1] if "." in host else "pl"
        self._session = None
        self._created_at = time.time()
        self._request_count = 0
        self._rotation_delay = 3  # OPTYMALIZACJA: 3s zamiast 4s
        self._last_rotation = time.time()
    
    def _create_session(self):
        """Tworzy nową sesję HTTP."""
        import requests
        from curl_cffi import requests as curl_requests
        
        try:
            self._session = curl_requests.Session(
                impersonate="chrome124",
                timeout=10,
            )
            self._session.headers.update(build_headers(self.host))
            self._request_count = 0
            self._created_at = time.time()
            logger.debug(f"Nowa sesja [{self.host}] utworzona")
        except ImportError:
            self._session = requests.Session()
            self._session.headers.update(build_headers(self.host))
            self._session.timeout = 10
            logger.debug(f"Nowa sesja requests [{self.host}] utworzona")
    
    def get(self, url: str, params: list = None, timeout: int = 10, **kwargs):
        """Wykonuje GET request z rate limitingiem per-domain."""
        if not check_rate_limit(self.domain):
            time.sleep(5)
        
        if self._session is None or time.time() - self._last_rotation > self._rotation_delay:
            if self._session:
                self.invalidate()
            self._create_session()
            self._last_rotation = time.time()
        
        self._request_count += 1
        human_delay(100, 300)
        
        try:
            response = self._session.get(url, params=params, timeout=timeout, **kwargs)
            return response
        except Exception as e:
            logger.error(f"Błąd request {url}: {e}")
            self.invalidate()
            raise
    
    def invalidate(self):
        """Unieważnia obecną sesję."""
        if self._session:
            try:
                self._session.close()
            except:
                pass
            self._session = None
        logger.debug(f"Sesja [{self.host}] unieważniona")
    
    def __del__(self):
        self.invalidate()
