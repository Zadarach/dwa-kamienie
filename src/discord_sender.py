"""
discord_sender.py - Wysyłanie powiadomień na Discord.
WERSJA: 4.0 - Price drop + Seller tracking + Hidden item alerts
"""
import time
import requests
from datetime import datetime, timezone
from src.logger import get_logger
logger = get_logger("discord")

_http_session = requests.Session()

COLOR_PRESETS = {
    "zielony": 0x57F287,
    "niebieski": 0x3498DB,
    "fioletowy": 0x9B59B6,
    "czerwony": 0xE74C3C,
    "pomarańcz": 0xE67E22,
    "żółty": 0xF1C40F,
    "różowy": 0xFF6B9D,
    "biały": 0xFFFFFF,
    "szary": 0x95A5A6,
    "czarny": 0x2C3E50,
    "turkus": 0x1ABC9C,
    "złoty": 0xFFD700,
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

def send_item_to_discord(item, webhook_url: str, query_name: str = "", embed_color: str = "5763719") -> bool:
    color = _parse_color(embed_color)
    
    if item.feedback_count > 0:
        score = min(item.feedback_score, 5.0)
        full = int(score)
        half = 1 if (score - full) >= 0.5 else 0
        stars = "⭐" * full + ("✨" if half else "") + ("☆" * (5 - full - half))
        rating_val = f"{stars} ({item.feedback_count})"
    else:
        rating_val = "☆☆☆☆☆ Brak ocen"

    price_val = f"**{item.price} {item.currency}** ({item.total_price})"
    seller_name = f"{item.country_flag} {item.user_login}" if item.user_login else "🌍 —"
    discord_relative = f"<t:{item.raw_timestamp}:R>"
    
    main_embed = {
        "author": {"name": seller_name, "url": item.user_url or item.url},
        "title": item.title,
        "url": item.url,
        "color": color,
        "fields": [
            {"name": "📅 Dodano", "value": discord_relative, "inline": True},
            {"name": "📐 Rozmiar", "value": item.size_title or "—", "inline": True},
            {"name": "🏷️ Marka", "value": item.brand_title or "—", "inline": True},
            {"name": "🧵 Stan", "value": item.status or "—", "inline": True},
            {"name": "✨ Ocena", "value": rating_val, "inline": True},
            {"name": "💰 Cena", "value": price_val, "inline": True},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if item.is_hidden:
        main_embed["footer"] = {"text": "⚠️ Ten przedmiot jest ukryty na Vinted - wymaga weryfikacji!"}
        main_embed["color"] = 0xFFA500  # Pomarańczowy dla ukrytych
    if item.photos:
        main_embed["image"] = {"url": item.photos[0]}

    embeds = [main_embed]
    for photo_url in item.photos[1:3]:
        embeds.append({"url": item.url, "color": color, "image": {"url": photo_url}})

    return _send_webhook(webhook_url, {"embeds": embeds})

def send_price_drop_alert(item, webhook_url: str, drop_amount: float, old_price: float) -> bool:
    """Wysyła alert o obniżce ceny."""
    try:
        price_float = float(item.price.replace(',', '.').replace(' ', ''))
        drop_percent = (drop_amount / old_price) * 100 if old_price > 0 else 0
    except:
        drop_percent = 0
    
    embed = {
        "title": f"💰 OBNIŻKA CENY! {item.title}",
        "url": item.url,
        "color": 0x00FF00,
        "fields": [
            {"name": "💸 Stara cena", "value": f"~~{old_price:.2f} {item.currency}~~", "inline": True},
            {"name": "🏷️ Nowa cena", "value": f"**{item.price} {item.currency}**", "inline": True},
            {"name": "📉 Oszczędzasz", "value": f"**{drop_amount:.2f} {item.currency}** (-{drop_percent:.1f}%)", "inline": True},
            {"name": "👤 Sprzedający", "value": f"{item.country_flag} {item.user_login}", "inline": True},
            {"name": "📅 Dodano", "value": f"<t:{item.raw_timestamp}:R>", "inline": True},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    if item.photos:
        embed["image"] = {"url": item.photos[0]}
    
    embed["footer"] = {"text": "🔥 Szybko kupuj zanim ktoś inny!"}
    
    return _send_webhook(webhook_url, {"embeds": [embed]})

def send_seller_alert(item, webhook_url: str) -> bool:
    """Wysyła alert o nowym przedmiocie od śledzonego sprzedawcy."""
    embed = {
        "author": {"name": f"👤 {item.user_login}", "url": item.user_url or item.url},
        "title": f"🆕 NOWY PRZEDMIOT! {item.title}",
        "url": item.url,
        "color": 0xFFD700,
        "fields": [
            {"name": "💰 Cena", "value": f"**{item.price} {item.currency}**", "inline": True},
            {"name": "📐 Rozmiar", "value": item.size_title or "—", "inline": True},
            {"name": "🧵 Stan", "value": item.status or "—", "inline": True},
            {"name": "📅 Dodano", "value": f"<t:{item.raw_timestamp}:R>", "inline": True},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    if item.photos:
        embed["image"] = {"url": item.photos[0]}
    
    embed["footer"] = {"text": "👤 Śledzony sprzedawca"}
    
    return _send_webhook(webhook_url, {"embeds": [embed]})

def send_system_message(webhook_url: str, message: str, level: str = "INFO") -> bool:
    colors = {"INFO": 0x3498DB, "SUCCESS": 0x57F287, "WARNING": 0xF1C40F, "ERROR": 0xE74C3C}
    emojis = {"INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "ERROR": "❌"}
    color = colors.get(level.upper(), 0x3498DB)
    emoji = emojis.get(level.upper(), "ℹ️")
    payload = {"embeds": [{"description": f"{emoji} {message}", "color": color, "footer": {"text": "Vinted-Notification"}, "timestamp": datetime.now(timezone.utc).isoformat()}]}
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
    logger.error("Discord: wszystkie próby nieudane")
    return False
