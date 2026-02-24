"""
discord_bot.py - Discord Bot z prawdziwymi przyciskami Link Button.
"""
import time
import requests
from datetime import datetime, timezone
from typing import Optional
from src.logger import get_logger

logger = get_logger("discord_bot")

DISCORD_API = "https://discord.com/api/v10"


class DiscordBot:

    def __init__(self, token: Optional[str] = None):
        self.token    = token
        self.enabled  = bool(token and token.strip())
        self._session = requests.Session()
        if self.enabled:
            self._session.headers.update({
                "Authorization": f"Bot {self.token}",
                "Content-Type":  "application/json",
                "User-Agent":    "DiscordBot (VintedNotification, 3.0)",
            })
            logger.info("Discord Bot API aktywny")
        else:
            logger.info("Discord Bot API wyłączony — używam webhooków")

    def send_item(self, item, channel_id: str, query_name: str = "",
                  embed_color: int = 0x57F287, webhook_url: str = "") -> bool:
        if self.enabled and channel_id:
            return self._send_via_bot(item, channel_id, query_name, embed_color)
        elif webhook_url:
            from src.discord_sender import send_item_to_discord
            return send_item_to_discord(
                item=item, webhook_url=webhook_url,
                query_name=query_name, embed_color=str(embed_color),
            )
        else:
            logger.error("Brak channel_id i webhook_url — nie można wysłać")
            return False

    def _send_via_bot(self, item, channel_id: str, query_name: str, embed_color: int) -> bool:

        # ── Ocena ────────────────────────────────────────
        if item.feedback_count > 0:
            score = min(item.feedback_score, 5.0)
            full  = int(score)
            half  = 1 if (score - full) >= 0.5 else 0
            empty = 5 - full - half
            stars = "⭐" * full + ("✨" if half else "") + "☆" * empty
            rating_val = f"{stars} ({item.feedback_count})"
        else:
            rating_val = "☆☆☆☆☆ Brak ocen"

        # ── Cena w jednej linii ───────────────────────────
        price_val = f"**{item.price} {item.currency}** ({item.total_price})"

        # ── Flaga kraju sprzedającego ─────────────────────
        seller_name = f"{item.country_flag} {item.user_login}" if item.user_login else "🌍 —"

        # ── Główny embed ──────────────────────────────────
        embed = {
            "author": {
                "name": seller_name,
                "url":  item.user_url or item.url,
            },
            "title":  item.title,
            "url":    item.url,
            "color":  embed_color,
            "fields": [
                # Pełna data + czas relatywny
                {"name": "📅 Dodano",  "value": f"<t:{item.raw_timestamp}:F>\n<t:{item.raw_timestamp}:R>", "inline": True},
                {"name": "📐 Rozmiar", "value": item.size_title or "—",  "inline": True},
                {"name": "🏷️ Marka",   "value": item.brand_title or "—", "inline": True},
                {"name": "🧵 Stan",    "value": item.status or "—",      "inline": True},
                {"name": "✨ Ocena",   "value": rating_val,               "inline": True},
                {"name": "💰 Cena",    "value": price_val,                "inline": True},
            ],
            "timestamp": item.created_at_ts.isoformat(),
        }

        if item.is_hidden:
            embed["footer"] = {
                "text": "⚠️ Ten przedmiot jest ukryty na Vinted – nie można go kupić!"
            }

        if item.photos:
            embed["image"] = {"url": item.photos[0]}

        embeds = [embed]
        for photo_url in item.photos[1:3]:
            embeds.append({"url": item.url, "color": embed_color, "image": {"url": photo_url}})

        components = [{
            "type": 1,
            "components": [
                {"type": 2, "style": 5, "label": "🛒 Kup teraz",     "url": item.buy_url},
                {"type": 2, "style": 5, "label": "💬 Wyślij ofertę", "url": item.offer_url},
                {"type": 2, "style": 5, "label": "❤️ Ulubione",      "url": item.favourite_url},
                {"type": 2, "style": 5, "label": "👤 Sprzedający",   "url": item.user_url or item.url},
            ],
        }]

        return self._post_message(channel_id, {"embeds": embeds, "components": components})

    def _post_message(self, channel_id: str, payload: dict, retries: int = 3) -> bool:
        url = f"{DISCORD_API}/channels/{channel_id}/messages"

        for attempt in range(1, retries + 1):
            try:
                resp = self._session.post(url, json=payload, timeout=15)

                if resp.status_code == 200:
                    return True
                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", 5))
                    logger.warning(f"Discord rate limit — czekam {wait:.1f}s")
                    time.sleep(wait + 0.5)
                    continue
                if resp.status_code == 401:
                    logger.error("Discord Bot: nieprawidłowy token!")
                    return False
                if resp.status_code == 403:
                    logger.error(f"Discord Bot: brak uprawnień do kanału {channel_id}.")
                    return False
                if resp.status_code == 404:
                    logger.error(f"Discord Bot: kanał {channel_id} nie istnieje")
                    return False

                logger.warning(f"Discord Bot: HTTP {resp.status_code} (próba {attempt}): {resp.text[:200]}")

            except requests.exceptions.Timeout:
                logger.warning(f"Discord Bot: timeout (próba {attempt})")
            except Exception as e:
                logger.error(f"Discord Bot: błąd {e}")
                return False

            if attempt < retries:
                time.sleep(2 ** attempt)

        return False

    def validate_token(self) -> bool:
        if not self.enabled:
            return False
        try:
            r = self._session.get(f"{DISCORD_API}/users/@me", timeout=10)
            if r.status_code == 200:
                data = r.json()
                logger.info(f"Discord Bot zalogowany jako: {data.get('username')}#{data.get('discriminator', '0')}")
                return True
            logger.error(f"Discord Bot: walidacja tokena nieudana ({r.status_code})")
            return False
        except Exception as e:
            logger.error(f"Discord Bot: błąd walidacji {e}")
            return False


_bot_instance: Optional[DiscordBot] = None


def get_bot() -> DiscordBot:
    global _bot_instance
    if _bot_instance is None:
        try:
            import src.database as db
            token = db.get_config("discord_bot_token", "")
            _bot_instance = DiscordBot(token=token if token else None)
        except Exception:
            _bot_instance = DiscordBot(token=None)
    return _bot_instance


def reload_bot():
    global _bot_instance
    _bot_instance = None
