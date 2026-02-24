"""
discord_sender.py - Wysyłanie powiadomień na Discord przez Webhooks.
"""
import time
import requests
from datetime import datetime, timezone
from src.logger import get_logger

logger = get_logger("discord")

_http_session = requests.Session()

COLOR_PRESETS = {
    "zielony":   0x57F287,
    "niebieski": 0x3498DB,
    "fioletowy": 0x9B59B6,
    "czerwony":  0xE74C3C,
    "pomarańcz": 0xE67E22,
    "żółty":     0xF1C40F,
    "różowy":    0xFF6B9D,
    "biały":     0xFFFFFF,
    "szary":     0x95A5A6,
    "czarny":    0x2C3E50,
    "turkus":    0x1ABC9C,
    "złoty":     0xFFD700,
}


def _parse_color(color_str: str) -> int:
    if isinstance(color_str, int):
        return color_str
    try:
        return int(color_str)
    except (ValueError, TypeError):
        try:
            return int(str(color_str).lstrip("#"), 16)
        except ValueError:
            return COLOR_PRESETS["zielony"]


def send_item_to_discord(
    item,
    webhook_url: str,
    query_name: str = "",
    embed_color: str = "5763719",
) -> bool:
    color = _parse_color(embed_color)

    # ── Ocena sprzedającego ───────────────────────────────
    if item.feedback_count > 0:
        score = min(item.feedback_score, 5.0)
        full  = int(score)
        half  = 1 if (score - full) >= 0.5 else 0
        empty = 5 - full - half
        stars = "⭐" * full + ("✨" if half else "") + "☆" * empty
        rating_val = f"{stars} ({item.feedback_count})"
    else:
        rating_val = "☆☆☆☆☆ Brak ocen"

    # ── Cena w jednej linii ───────────────────────────────
    price_val = f"**{item.price} {item.currency}** ({item.total_price})"

    # ── Flaga kraju sprzedającego w nazwie autora ─────────
    # country_flag pochodzi z danych użytkownika (enrichment w core.py)
    seller_name = f"{item.country_flag} {item.user_login}" if item.user_login else "🌍 —"

    # ── Główny embed ──────────────────────────────────────
    main_embed = {
        "author": {
            "name": seller_name,
            "url":  item.user_url or item.url,
        },
        "title": item.title,
        "url":   item.url,
        "color": color,
        "fields": [
            # Pełna data + czas relatywny — dwa formaty Discord naraz
            # <t:X:F> = "niedziela, 22 lutego 2026 17:36" (pełna data)
            # <t:X:R> = "godzinę temu" (aktualizuje się na żywo)
            {"name": "📅 Dodano",   "value": f"<t:{item.raw_timestamp}:F>\n<t:{item.raw_timestamp}:R>", "inline": True},
            {"name": "📐 Rozmiar",  "value": item.size_title or "—",  "inline": True},
            {"name": "🏷️ Marka",    "value": item.brand_title or "—", "inline": True},
            {"name": "🧵 Stan",     "value": item.status or "—",      "inline": True},
            {"name": "✨ Ocena",    "value": rating_val,               "inline": True},
            {"name": "💰 Cena",     "value": price_val,                "inline": True},
        ],
        "timestamp": item.created_at_ts.isoformat(),
    }

    # Ostrzeżenie o ukrytym przedmiocie
    if item.is_hidden:
        main_embed["footer"] = {
            "text": "⚠️ Ten przedmiot jest ukryty na Vinted – nie można go kupić!"
        }

    if item.photos:
        main_embed["image"] = {"url": item.photos[0]}

    # Dodatkowe embedy (galeria zdjęć 2 i 3)
    embeds = [main_embed]
    for photo_url in item.photos[1:3]:
        embeds.append({
            "url":   item.url,
            "color": color,
            "image": {"url": photo_url},
        })

    return _send_webhook(webhook_url, {"embeds": embeds})


def send_system_message(webhook_url: str, message: str, level: str = "INFO") -> bool:
    colors = {"INFO": 0x3498DB, "SUCCESS": 0x57F287, "WARNING": 0xF1C40F, "ERROR": 0xE74C3C}
    emojis = {"INFO": "ℹ️",    "SUCCESS": "✅",      "WARNING": "⚠️",     "ERROR": "❌"}
    color  = colors.get(level.upper(), 0x3498DB)
    emoji  = emojis.get(level.upper(), "ℹ️")

    payload = {
        "embeds": [{
            "description": f"{emoji} {message}",
            "color": color,
            "footer": {"text": "Vinted-Notification"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }
    return _send_webhook(webhook_url, payload)


def _send_webhook(webhook_url: str, payload: dict, retries: int = 3) -> bool:
    for attempt in range(1, retries + 1):
        try:
            resp = _http_session.post(webhook_url, json=payload, timeout=10)

            if resp.status_code == 204:
                return True

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 5))
                logger.warning(f"Discord rate limit — czekam {retry_after:.1f}s")
                time.sleep(retry_after + 1)
                continue

            if resp.status_code in (400, 401, 403, 404):
                logger.error(f"Discord webhook błąd {resp.status_code}: {resp.text[:300]}")
                return False

            logger.warning(f"Discord HTTP {resp.status_code} (próba {attempt}/{retries})")

        except requests.exceptions.Timeout:
            logger.warning(f"Discord timeout (próba {attempt}/{retries})")
        except Exception as e:
            logger.error(f"Discord wyjątek: {e}")
            return False

        if attempt < retries:
            time.sleep(1.5 ** attempt)

    logger.error("Discord: wszystkie próby wysyłki nieudane")
    return False
