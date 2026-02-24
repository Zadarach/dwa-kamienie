import time
import requests
from requests.exceptions import HTTPError


class Requester:

    def __init__(self):
        self.VINTED_AUTH_URL = "https://www.vinted.pl/"
        self.MAX_RETRIES = 3
        self.session = requests.Session()
        self._set_headers("www.vinted.pl")

    def _set_headers(self, host: str):
        """Ustawia nagłówki imitujące przeglądarkę Chrome."""
        self.session.headers.clear()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": f"https://{host}/",
            "Origin": f"https://{host}",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        })

    def setLocale(self, locale: str):
        self.VINTED_AUTH_URL = f"https://{locale}/"
        self._set_headers(locale)

    def setCookies(self):
        """
        Pobiera cookies sesyjne od Vinted.
        Vinted wymaga GET (nie HEAD) żeby zwrócić pełne cookies.
        """
        self.session.cookies.clear()
        try:
            r = self.session.get(
                self.VINTED_AUTH_URL,
                timeout=15,
                allow_redirects=True,
            )
            if r.status_code == 200:
                print(f"[Requester] Cookies pobrane ({len(self.session.cookies)} szt.)")
            else:
                print(f"[Requester] Cookies: status {r.status_code}")
        except Exception as e:
            print(f"[Requester] Blad pobierania cookies: {e}")

    def get(self, url: str, params=None):
        """
        GET request z automatycznym odnawianiem cookies.
        """
        if not self.session.cookies:
            self.setCookies()

        tried = 0
        while tried < self.MAX_RETRIES:
            tried += 1
            try:
                response = self.session.get(url, params=params, timeout=15)

                if response.status_code == 200:
                    return response

                elif response.status_code in (401, 403):
                    print(f"[Requester] {response.status_code} — odnawianie cookies (proba {tried})")
                    self.setCookies()
                    time.sleep(2)
                    continue

                elif response.status_code == 404:
                    if tried == 1:
                        print(f"[Requester] 404 — proba odnowienia cookies")
                        self.setCookies()
                        time.sleep(2)
                        continue
                    return response

                elif response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", 10))
                    print(f"[Requester] Rate limit — czekam {retry_after}s")
                    time.sleep(retry_after)
                    continue

                else:
                    return response

            except requests.exceptions.Timeout:
                print(f"[Requester] Timeout (proba {tried}/{self.MAX_RETRIES})")
                if tried == self.MAX_RETRIES:
                    raise
                time.sleep(2)

            except requests.exceptions.ConnectionError as e:
                print(f"[Requester] Blad polaczenia: {e} (proba {tried})")
                if tried == self.MAX_RETRIES:
                    raise
                time.sleep(3)

            except Exception as e:
                if tried == self.MAX_RETRIES:
                    raise e
                time.sleep(1)

        raise HTTPError(f"Max retries ({self.MAX_RETRIES}) exceeded")


requester = Requester()
