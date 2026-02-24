from datetime import datetime, timezone
from typing import List


class Item:
    __slots__ = (
        'id', 'title', 'brand_title', 'size_title', 'currency', 'price',
        'status', 'status_id', 'url', 'buy_url', 'offer_url', 'favourite_url',
        'photos', 'photo', 'raw_timestamp', 'created_at_ts',
        'user_id', 'user_login', 'user_country', 'user_url',
        'feedback_count', 'feedback_score', 'country_flag',
        'total_price', 'domain', 'is_hidden',
    )

    STATUS_MAP = {
        1: "Nowy z metką",
        2: "Nowy bez metki",
        3: "Bardzo dobry",
        4: "Dobry",
        5: "Zadowalający",
    }

    COUNTRY_FLAGS = {
        "PL": "🇵🇱", "DE": "🇩🇪", "FR": "🇫🇷", "GB": "🇬🇧", "IT": "🇮🇹",
        "ES": "🇪🇸", "NL": "🇳🇱", "BE": "🇧🇪", "AT": "🇦🇹", "CZ": "🇨🇿",
        "SK": "🇸🇰", "HU": "🇭🇺", "RO": "🇷🇴", "SE": "🇸🇪", "FI": "🇫🇮",
        "DK": "🇩🇰", "NO": "🇳🇴", "PT": "🇵🇹", "LT": "🇱🇹", "LV": "🇱🇻",
        "EE": "🇪🇪", "HR": "🇭🇷", "SI": "🇸🇮", "LU": "🇱🇺", "US": "🇺🇸",
    }

    DOMAIN_TO_COUNTRY = {
        "pl": "PL", "de": "DE", "fr": "FR", "it": "IT", "es": "ES",
        "nl": "NL", "be": "BE", "at": "AT", "cz": "CZ", "sk": "SK",
        "hu": "HU", "ro": "RO", "se": "SE", "fi": "FI", "dk": "DK",
        "no": "NO", "pt": "PT", "lt": "LT", "lv": "LV", "ee": "EE",
        "hr": "HR", "si": "SI", "lu": "LU", "com": "US",
    }

    def __init__(self, data: dict, domain: str = "pl"):
        self.domain    = domain.lower() if domain else "pl"
        self.id        = data["id"]
        self.title     = data.get("title", "Brak tytułu")
        self.brand_title = data.get("brand_title", "—")
        self.is_hidden = bool(data.get("is_hidden", 0))

        # Rozmiar — API zwraca string lub dict
        size_raw = data.get("size_title") or data.get("size")
        self.size_title = (
            size_raw.get("title", "—") if isinstance(size_raw, dict) else (size_raw or "—")
        )

        # Cena
        price_data = data.get("price", {})
        if isinstance(price_data, dict):
            self.currency = price_data.get("currency_code", "PLN")
            self.price    = price_data.get("amount", "0")
        else:
            self.currency = "PLN"
            self.price    = str(price_data)

        # Stan — API zwraca string, dict lub int
        status_raw = data.get("status")
        if isinstance(status_raw, str):
            self.status    = status_raw
            self.status_id = None
        elif isinstance(status_raw, dict):
            self.status_id = status_raw.get("id")
            self.status    = status_raw.get("title") or self.STATUS_MAP.get(self.status_id, "—")
        else:
            self.status_id = data.get("status_id")
            self.status    = self.STATUS_MAP.get(self.status_id, "—")

        # URL przedmiotu
        base_url = f"https://www.vinted.{self.domain}"
        raw_url  = data.get("url", "")
        self.url = raw_url if raw_url.startswith("http") else f"{base_url}{raw_url}"

        # Linki akcji
        self.buy_url       = (
            f"{base_url}/transaction/buy/new"
            f"?source_screen=item&transaction%5Bitem_id%5D={self.id}"
        )
        self.offer_url     = f"{self.url}?ref=offer"
        self.favourite_url = f"{self.url}?ref=fav"

        # Zdjęcia (max 3)
        self.photos: List[str] = self._extract_photos(data)
        self.photo = self.photos[0] if self.photos else None

        # Timestamp
        self.raw_timestamp = self._extract_timestamp(data)
        self.created_at_ts = datetime.fromtimestamp(self.raw_timestamp, tz=timezone.utc)

        # Użytkownik / sprzedający
        user_data = data.get("user", {})
        if isinstance(user_data, dict):
            self.user_id      = user_data.get("id")
            self.user_login   = user_data.get("login", "—")
            self.user_country = (
                user_data.get("country_iso_code")
                or user_data.get("country_code")
                or ""
            )
            self.user_url = f"{base_url}/member/{self.user_id}" if self.user_id else None

            # Ocena z danych API katalogu (często puste — enrichment w core.py)
            fc = (
                user_data.get("feedback_count")
                or user_data.get("positive_feedback_count")
                or 0
            )
            try:
                self.feedback_count = int(fc) if fc else 0
            except (ValueError, TypeError):
                self.feedback_count = 0

            raw_rep_val = (
                user_data.get("feedback_reputation")
                or user_data.get("reputation")
                or user_data.get("feedback_score")
            )
            try:
                raw_rep = float(raw_rep_val) if raw_rep_val is not None else 0.0
            except (ValueError, TypeError):
                raw_rep = 0.0

            if 0 < raw_rep <= 1:
                self.feedback_score = raw_rep * 5
            elif raw_rep > 5:
                self.feedback_score = raw_rep / 20
            else:
                self.feedback_score = raw_rep
        else:
            self.user_id = self.user_login = self.user_url = None
            self.user_country   = ""
            self.feedback_count = 0
            self.feedback_score = 0.0

        # Kraj → flaga emoji
        country_code = self.user_country.upper() if self.user_country else ""
        if not country_code or country_code not in self.COUNTRY_FLAGS:
            country_code = self.DOMAIN_TO_COUNTRY.get(self.domain, "")
        self.country_flag = self.COUNTRY_FLAGS.get(country_code, "🌍")

        # Cena łączna (z ochroną kupującego: ~6% + 0.30)
        self.total_price = self._calculate_total()

    def _extract_photos(self, data: dict) -> List[str]:
        photos = []
        for p in data.get("photos", [])[:3]:
            if isinstance(p, dict):
                url = p.get("url") or p.get("full_size_url")
                if url:
                    photos.append(url)
        if not photos:
            main = data.get("photo", {})
            if isinstance(main, dict) and main.get("url"):
                photos.append(main["url"])
        return photos[:3]

    def _extract_timestamp(self, data: dict) -> int:
        if data.get("created_at_ts"):
            return int(data["created_at_ts"])
        photo = data.get("photo", {})
        if isinstance(photo, dict):
            hr = photo.get("high_resolution", {})
            if isinstance(hr, dict) and hr.get("timestamp"):
                return int(hr["timestamp"])
        return int(datetime.now(tz=timezone.utc).timestamp())

    def _calculate_total(self) -> str:
        try:
            p     = float(self.price)
            total = p + p * 0.06 + 0.30
            return f"≈ {total:.2f} {self.currency}"
        except (ValueError, TypeError):
            return "—"

    def get_stars(self) -> str:
        """
        Ocena jako emoji gwiazdki (max 5).
        Przykład: 4 gwiazdki na 5 → ⭐⭐⭐⭐☆
        Pół gwiazdki → ⭐⭐⭐⭐✨
        """
        score = min(self.feedback_score, 5.0)
        full  = int(score)
        half  = 1 if (score - full) >= 0.5 else 0
        empty = 5 - full - half
        return "⭐" * full + ("✨" if half else "") + "☆" * empty

    def get_time_ago(self) -> str:
        s = int((datetime.now(timezone.utc) - self.created_at_ts).total_seconds())
        if s < 10:    return "🔴 TERAZ!"
        if s < 60:    return f"{s}s temu"
        if s < 3600:  return f"{s // 60} min temu"
        if s < 86400: return f"{s // 3600} godz. temu"
        return f"{s // 86400} dni temu"

    def is_new_item(self, minutes: int = 5) -> bool:
        return (datetime.now(timezone.utc) - self.created_at_ts).total_seconds() < minutes * 60

    def __eq__(self, other):  return isinstance(other, Item) and self.id == other.id
    def __hash__(self):       return hash(self.id)
    def __repr__(self):       return f"<Item {self.id} '{self.title}' {self.price}{self.currency}>"
