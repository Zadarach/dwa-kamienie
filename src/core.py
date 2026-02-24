"""
core.py - Logika scrapowania Vinted.
NAPRAWIONO: Mechanizm deduplikacji (zapobieganie podwójnym wysyłkom).
"""
import time
import queue
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs, parse_qsl, urlencode, urlunparse
import src.database as db
from src.pyVinted.items.item import Item
from src.discord_sender import send_item_to_discord
from src.discord_bot import get_bot
from src.anti_ban import SessionManager, human_delay, scan_jitter, backoff
from src.proxy_manager import proxy_manager
from src.config import extract_domain_from_url, get_api_base_url
from src.logger import get_logger
logger = get_logger("core")

items_queue: queue.Queue = queue.Queue(maxsize=200)

# In-memory dedup — ochrona przed duplikatami w ramach jednej sesji
from collections import deque as _deque
_queued_ids_deque: _deque = _deque(maxlen=500)
_queued_ids_set:   set    = set()

def _is_already_queued(vinted_id: str) -> bool:
    return str(vinted_id) in _queued_ids_set

def _mark_queued(vinted_id: str):
    sid = str(vinted_id)
    if len(_queued_ids_deque) == _queued_ids_deque.maxlen:
        oldest = _queued_ids_deque[0]
        _queued_ids_set.discard(oldest)
        _queued_ids_deque.append(sid)
        _queued_ids_set.add(sid)

_session_managers: dict = {}
_session_last_used: dict = {}
_SM_TTL_SECONDS = 30 * 60

_user_rating_cache: dict = {}
_USER_CACHE_TTL = 3600

def _get_session_manager(domain: str) -> SessionManager:
    host = f"www.vinted.{domain}"
    if host not in _session_managers:
        _session_managers[host] = SessionManager(host=host)
        _session_last_used[host] = time.time()
    return _session_managers[host]

def _cleanup_stale_sessions():
    now = time.time()
    stale = [h for h, ts in _session_last_used.items() if now - ts > _SM_TTL_SECONDS]
    for host in stale:
        sm = _session_managers.pop(host, None)
        _session_last_used.pop(host, None)
        if sm:
            logger.info(f"Cleanup: usunięto sesję {host} (nieużywana >30min)")

def warmup(domain: str = "pl"):
    logger.info(f"Inicjalizacja sesji HTTP (vinted.{domain})…")
    try:
        sm = _get_session_manager(domain)
        api_url = get_api_base_url(domain)
        sm.get(api_url, params=[("per_page", "1"), ("order", "newest_first")])
        logger.info("Sesja gotowa")
    except Exception as e:
        logger.warning(f"Warmup nieudany (spróbuję przy pierwszym skanie): {e}")

def normalize_query_url(url: str) -> str:
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "brand":
        brand_id = parts[1].split("-")[0]
        parsed = parsed._replace(path="/catalog", query=f"brand_ids[]={brand_id}")
    
    url_params = parse_qsl(parsed.query, keep_blank_values=False)
    skip = {"time", "search_id", "disabled_personalization", "page"}
    filtered = [(k, v) for k, v in url_params if k not in skip]

    if not any(k == "order" for k, _ in filtered):
        filtered.append(("order", "newest_first"))
    else:
        filtered = [(k, "newest_first") if k == "order" else (k, v) for k, v in filtered]

    return urlunparse(parsed._replace(query=urlencode(filtered)))

_PARAM_MAP = {
    "catalog[]":      "catalog_ids[]",
    "status[]":       "status_ids[]",
    "size_ids[]":     "size_ids[]",
    "brand_ids[]":    "brand_ids[]",
    "color_ids[]":    "color_ids[]",
    "material_ids[]": "material_ids[]",
    "country_ids[]":  "country_ids[]",
    "city_ids[]":     "city_ids[]",
    "disposal[]":     "disposal[]",
    "price_from":     "price_from",
    "price_to":       "price_to",
    "currency":       "currency",
    "search_text":    "search_text",
}

_SKIP_PARAMS = {
    "time", "search_id", "page", "disabled_personalization",
    "ref", "utm_source", "utm_medium", "utm_campaign",
}

def _build_api_params(query_url: str, per_page: int) -> list:
    parsed = urlparse(query_url)
    url_params = parse_qsl(parsed.query, keep_blank_values=False)
    api_params = []
    
    for k, v in url_params:
        if k in _SKIP_PARAMS:
            continue
        mapped_key = _PARAM_MAP.get(k, k)
        api_params.append((mapped_key, v))

    api_params.append(("per_page", str(per_page)))

    if not any(k == "order" for k, _ in api_params):
        api_params.append(("order", "newest_first"))
    
    api_params.append(("with_disabled_items", "1"))
    logger.debug(f"API params: {api_params}")
    return api_params

def _fetch_user_rating(user_id: int, sm: SessionManager, domain: str) -> tuple:
    if not user_id:
        return 0, 0.0, ""
    now = time.time()

    if user_id in _user_rating_cache:
        cached = _user_rating_cache[user_id]
        if now < cached[3]:
            return cached[0], cached[1], cached[2]

    try:
        api_url = f"https://www.vinted.{domain}/api/v2/users/{user_id}"
        r = sm.get(api_url, timeout=6)

        if r.status_code == 200:
            user_data = r.json().get("user", {})
            fc = user_data.get("feedback_count") or user_data.get("positive_feedback_count") or 0
            try:
                count = int(fc) if fc else 0
            except (ValueError, TypeError):
                count = 0

            raw_rep_val = user_data.get("feedback_reputation") or user_data.get("reputation") or 0
            try:
                raw_rep = float(raw_rep_val)
            except (ValueError, TypeError):
                raw_rep = 0.0

            if 0 < raw_rep <= 1:
                score = raw_rep * 5
            elif raw_rep > 5:
                score = raw_rep / 20
            else:
                score = raw_rep

            from src.pyVinted.items.item import Item as _Item
            country_code = (
                user_data.get("country_iso_code")
                or user_data.get("country_code")
                or user_data.get("city", {}).get("country_iso_code", "")
                or ""
            ).upper()
            country_flag = _Item.COUNTRY_FLAGS.get(country_code, "")

            _user_rating_cache[user_id] = (count, score, country_flag, now + _USER_CACHE_TTL)

            if len(_user_rating_cache) > 500:
                oldest = sorted(_user_rating_cache.items(), key=lambda x: x[1][3])[:100]
                for uid, _ in oldest:
                    _user_rating_cache.pop(uid, None)

            return count, score, country_flag

    except Exception as e:
        logger.debug(f"Błąd pobierania danych user {user_id}: {e}")

    return 0, 0.0, ""

def _fetch_items(query_url: str, per_page: int = 20):
    domain = extract_domain_from_url(query_url)
    api_url = get_api_base_url(domain)
    sm = _get_session_manager(domain)
    api_params = _build_api_params(query_url, per_page)
    
    for attempt in range(1, 4):
        try:
            proxy = proxy_manager.get_proxy_dict()

            if proxy:
                from src.anti_ban import build_headers
                import requests as _req
                host = f"www.vinted.{domain}"
                headers = dict(sm._session.headers) if sm._session else build_headers(host)
                r = _req.get(api_url, params=api_params, timeout=10, proxies=proxy, headers=headers)
            else:
                r = sm.get(api_url, params=api_params, timeout=10)

            if r.status_code == 200 and not r.text.strip():
                logger.warning(f"Puste body (próba {attempt}/3) — rotacja sesji")
                sm.invalidate()
                time.sleep(backoff(attempt))
                continue

            if r.status_code in (401, 403):
                logger.warning(f"HTTP {r.status_code} (próba {attempt}/3) — rotacja sesji")
                sm.invalidate()
                time.sleep(backoff(attempt))
                continue

            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 20))
                logger.warning(f"Rate limit Vinted — czekam {wait:.0f}s")
                time.sleep(wait + random.uniform(1, 5))
                continue

            if r.status_code != 200:
                logger.error(f"API: HTTP {r.status_code}")
                return []

            try:
                data = r.json()
            except Exception:
                logger.warning(f"Nie-JSON (próba {attempt}/3) — rotacja sesji")
                sm.invalidate()
                time.sleep(backoff(attempt))
                continue

            items = [Item(it, domain=domain) for it in data.get("items", [])]

            # Enrichment: oceny sprzedających
            users_to_fetch = {
                it.user_id for it in items
                if it.user_id and it.feedback_count == 0
            }

            if users_to_fetch:
                def _fetch_one(uid):
                    return uid, _fetch_user_rating(uid, sm, domain)

                with ThreadPoolExecutor(max_workers=min(len(users_to_fetch), 5)) as ex:
                    futures = {ex.submit(_fetch_one, uid): uid for uid in users_to_fetch}
                    ratings = {}
                    for future in as_completed(futures):
                        try:
                            uid, (count, score, flag) = future.result()
                            ratings[uid] = (count, score, flag)
                        except Exception:
                            pass

                for it in items:
                    if it.user_id and it.user_id in ratings:
                        count, score, flag = ratings[it.user_id]
                        if count > 0:
                            it.feedback_count = count
                            it.feedback_score = score
                        if flag:
                            it.country_flag = flag

            return items

        except Exception as e:
            logger.error(f"Błąd (próba {attempt}/3): {e}")
            if attempt < 3:
                time.sleep(backoff(attempt))

    logger.error("3 próby nieudane — pomijam zapytanie")
    return []

def _fetch_single_query(query: dict, items_per_query: int, new_item_window: int) -> tuple:
    query_id = query["id"]
    query_url = query["url"]
    query_name = query["name"]
    last_ts = query["last_item_ts"]
    try:
        all_items = _fetch_items(query_url, per_page=items_per_query)
        new_items = [it for it in all_items if it.is_new_item(minutes=new_item_window)]
        results = []

        for item in reversed(new_items):
            if last_ts and item.raw_timestamp <= last_ts:
                continue
            
            # Dedup - sprawdzenie przed dodaniem do kolejki
            if _is_already_queued(item.id) or db.item_exists(str(item.id)):
                continue
            
            _mark_queued(item.id)
            results.append({
                "item": item,
                "query_id": query_id,
                "query_name": query_name,
                "webhook_url": query["discord_webhook_url"],
                "channel_id": query["discord_channel_id"],
                "embed_color": query["embed_color"],
            })

        return (query_name, len(new_items), len(all_items), results)

    except Exception as e:
        logger.error(f"Błąd [{query_name}]: {e}", exc_info=True)
        db.add_log("ERROR", "scraper", f"Błąd [{query_name}]: {str(e)}")
        return (query_name, 0, 0, [])

def scrape_all_queries():
    _cleanup_stale_sessions()
    queries = db.get_all_queries(active_only=True)
    if not queries:
        logger.debug("Brak aktywnych zapytań")
        return

    items_per_query = int(db.get_config("items_per_query", "20"))
    new_item_window = int(db.get_config("new_item_window", "2"))

    proxy_stats = proxy_manager.get_stats()
    proxy_info = f"{proxy_stats['total_proxies']} proxy" if proxy_stats["has_proxy"] else "direct"
    logger.info(f"Skan {len(queries)} zapytań | okno {new_item_window}min | {proxy_info}")

    max_workers = min(len(queries), 8)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(_fetch_single_query, q, items_per_query, new_item_window): q
            for q in queries
        }
        for future in as_completed(futures):
            try:
                query_name, n_new, n_all, results = future.result()
                if n_new > 0:
                    logger.info(f"[{query_name}] {n_new}/{n_all} nowych")
                else:
                    logger.debug(f"[{query_name}] 0/{n_all} nowych")
                for r in results:
                    items_queue.put(r)
            except Exception as e:
                logger.error(f"Błąd future: {e}")

def process_items_queue():
    """Konsumuje queue i wysyła na Discord."""
    try:
        from main import _metrics
    except ImportError:
        _metrics = None
        
    while not items_queue.empty():
        try:
            entry = items_queue.get_nowait()
        except queue.Empty:
            break

        item = entry["item"]
        query_id = entry["query_id"]
        query_name = entry["query_name"]
        webhook_url = entry["webhook_url"]
        channel_id = entry.get("channel_id", "")
        embed_color = entry["embed_color"]

        try:
            # 🔒 PODWÓJNE SPRAWDZENIE BAZY PRZED WYSYŁKĄ
            # To jest kluczowe, aby uniknąć duplikatów przy restarcie bota
            vinted_id_str = str(item.id)
            if db.item_exists(vinted_id_str):
                logger.debug(f"Duplikat (DB check przed wysyłką): {vinted_id_str}")
                db.update_query_last_ts(query_id, item.raw_timestamp)
                continue

            bot = get_bot()
            success = False
            
            if bot.enabled and channel_id:
                success = bot.send_item(
                    item=item,
                    channel_id=channel_id,
                    query_name=query_name,
                    embed_color=int(embed_color) if embed_color else 0x57F287,
                    webhook_url=webhook_url,
                )
            else:
                success = send_item_to_discord(
                    item=item,
                    webhook_url=webhook_url,
                    query_name=query_name,
                    embed_color=embed_color,
                )

            if success:
                # ✅ NATYCHMIASTOWY ZAPIS DO BAZY PO WYSYŁCE
                # Najpierw zapisujemy ID, żeby nawet przy crashu nie wysłać ponownie
                db.add_item(
                    vinted_id=vinted_id_str,
                    title=item.title,
                    brand=item.brand_title,
                    price=str(item.price),
                    currency=item.currency,
                    size=item.size_title or "",
                    status=item.status or "",
                    photo_url=item.photo or "",
                    item_url=item.url,
                    query_id=query_id,
                    timestamp=item.raw_timestamp,
                )
                
                # Aktualizacja metryk i logów
                if _metrics:
                    _metrics["items_sent_total"] += 1
                    
                hidden_tag = " [UKRYTY]" if item.is_hidden else ""
                db.update_query_last_ts(query_id, item.raw_timestamp)
                db.increment_query_items_found(query_id)
                db.add_log("SUCCESS", "sender",
                    f"✅{hidden_tag} {item.title} — {item.price} {item.currency} → #{query_name}")
                logger.info(f"✅{hidden_tag} {item.title} ({item.price} {item.currency})")
            else:
                db.add_log("ERROR", "sender", f"❌ Błąd wysyłki: {item.title}")

        except Exception as e:
            logger.error(f"Błąd przetwarzania {item.id}: {e}", exc_info=True)

        time.sleep(0.15)
