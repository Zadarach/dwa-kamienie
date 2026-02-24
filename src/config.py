"""
config.py - Stałe i konfiguracja Vinted-Notification.

Obsługiwane domeny Vinted (API działa identycznie na wszystkich):
https://www.vinted.{domain}/api/v2/catalog/items
"""
import re
from urllib.parse import urlparse

# Wszystkie oficjalne domeny Vinted (EU + UK)
VINTED_DOMAINS = [
    "pl", "de", "fr", "it", "es", "nl", "be", "at", "cz", "sk",
    "hu", "ro", "se", "fi", "dk", "no", "pt", "lt", "lv", "ee",
    "hr", "si", "lu", "gr", "com",  # com = vinted.com (international)
]

# Regex do wyciągania domeny z URL
DOMAIN_PATTERN = re.compile(
    r"https?://(?:www\.)?vinted\.([a-z]{2,3})",
    re.IGNORECASE
)


def extract_domain_from_url(url: str) -> str:
    """
    Wyciąga domenę Vinted z URL (np. vinted.pl -> pl).
    Domyślnie zwraca 'pl' jeśli nie rozpoznano.
    """
    if not url or not url.strip():
        return "pl"
    match = DOMAIN_PATTERN.search(url.strip())
    if match:
        domain = match.group(1).lower()
        if domain in VINTED_DOMAINS:
            return domain
    return "pl"


def get_api_base_url(domain: str) -> str:
    """Zwraca bazowy URL API dla danej domeny."""
    return f"https://www.vinted.{domain}/api/v2/catalog/items"


def get_site_base_url(domain: str) -> str:
    """Zwraca bazowy URL strony Vinted dla danej domeny."""
    return f"https://www.vinted.{domain}"


def normalize_domain(domain: str) -> str:
    """Sprawdza i normalizuje domenę."""
    d = (domain or "pl").lower().strip()
    return d if d in VINTED_DOMAINS else "pl"
