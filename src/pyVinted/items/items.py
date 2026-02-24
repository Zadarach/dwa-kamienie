from typing import List, Optional
from urllib.parse import urlparse, parse_qsl, urlencode
from requests.exceptions import HTTPError

from .item import Item
from ..requester import requester
from ..settings import Urls


class Items:

    def search(
        self,
        url: str,
        nbr_items: int = 20,
        page: int = 1,
        time: Optional[int] = None,
        as_json: bool = False,
    ) -> List[Item]:
        """
        Pobiera przedmioty z podanego URL wyszukiwania Vinted.
        """
        locale = urlparse(url).netloc
        requester.setLocale(locale)

        # Upewnij sie ze mamy cookies
        if not requester.session.cookies:
            requester.setCookies()

        params = self._parse_url(url, nbr_items, page, time)
        api_url = f"https://{locale}{Urls.VINTED_API_URL}/{Urls.VINTED_PRODUCTS_ENDPOINT}"

        # Debug — pokazuje dokladny URL wysylany do API
        debug_url = api_url + "?" + urlencode(params)
        print(f"[Items.search] Zapytanie: {debug_url}")

        try:
            response = requester.get(url=api_url, params=params)
            response.raise_for_status()
            data = response.json()
            items_data = data.get("items", [])
            print(f"[Items.search] Odpowiedz: {len(items_data)} przedmiotow")
            if as_json:
                return items_data
            return [Item(item) for item in items_data]

        except HTTPError as err:
            # Pokaz tresc odpowiedzi zeby zobaczyc co Vinted zwraca
            try:
                print(f"[Items.search] Tresc bledu: {err.response.text[:300]}")
            except Exception:
                pass
            raise err
        except Exception as e:
            print(f"[Items.search] Blad: {e}")
            return []

    def _parse_url(self, url: str, nbr_items: int = 20, page: int = 1, time=None) -> list:
        """
        Parsuje URL Vinted do listy parametrow API.

        Vinted API akceptuje brand_ids[] jako osobne klucze:
          brand_ids[]=362&brand_ids[]=872289
        """
        queries = parse_qsl(urlparse(url).query)

        def extract_list(key):
            return [v for k, v in queries if k == key]

        def extract_single(key):
            vals = [v for k, v in queries if k == key]
            return vals[0] if vals else None

        order = extract_single("order") or "newest_first"

        params = []

        # Marki
        for v in extract_list("brand_ids[]"):
            params.append(("brand_ids[]", v))

        # Kategorie
        for v in extract_list("catalog[]"):
            params.append(("catalog_ids[]", v))

        # Rozmiary
        for v in extract_list("size_ids[]"):
            params.append(("size_ids[]", v))

        # Kolory
        for v in extract_list("color_ids[]"):
            params.append(("color_ids[]", v))

        # Materialy
        for v in extract_list("material_ids[]"):
            params.append(("material_ids[]", v))

        # Stan
        for v in extract_list("status[]"):
            params.append(("status_ids[]", v))

        # Kraje
        for v in extract_list("country_ids[]"):
            params.append(("country_ids[]", v))

        # Miasta
        for v in extract_list("city_ids[]"):
            params.append(("city_ids[]", v))

        # Tekst wyszukiwania
        search_text = "+".join(v for k, v in queries if k == "search_text")
        if search_text:
            params.append(("search_text", search_text))

        # Waluta i cena
        currency = extract_single("currency")
        if currency:
            params.append(("currency", currency))

        price_to = extract_single("price_to")
        if price_to:
            params.append(("price_to", price_to))

        price_from = extract_single("price_from")
        if price_from:
            params.append(("price_from", price_from))

        # Swap
        if any(k == "disposal[]" for k, v in queries):
            params.append(("is_for_swap", "1"))

        # Stale parametry
        params.append(("page", str(page)))
        params.append(("per_page", str(nbr_items)))
        params.append(("order", order))

        if time is not None:
            params.append(("time", str(time)))

        return params
