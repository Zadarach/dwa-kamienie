def _fetch_single_query_multi_url(query: dict, items_per_query: int, new_item_window: int) -> tuple:
    """
    Pobiera itemy dla jednego zapytania z WIELOMA URLami.
    Każdy URL jest traktowany jako osobne źródło, ale wyniki trafiają do jednego kanału.
    """
    query_id = query["id"]
    query_name = query["name"]
    query_urls = query.get("urls", [])
    
    if not query_urls:
        logger.warning(f"[{query_name}] Brak URLi do skanowania!")
        return (query_name, 0, 0, [])
    
    all_results = []
    total_new = 0
    total_all = 0
    
    for url_entry in query_urls:
        url = url_entry["url"] if isinstance(url_entry, dict) else url_entry
        last_ts = url_entry.get("last_item_ts", query.get("last_item_ts", 0)) if isinstance(url_entry, dict) else query.get("last_item_ts", 0)
        
        try:
            items = _fetch_items(url, per_page=items_per_query)
            new_items = [it for it in items if it.is_new_item(minutes=new_item_window)]
            
            for item in reversed(new_items):
                if last_ts and item.raw_timestamp <= last_ts:
                    continue
                
                # Dedup
                if _is_already_queued(item.id) or db.item_exists(str(item.id)):
                    continue
                
                _mark_queued(item.id)
                all_results.append({
                    "item": item,
                    "query_id": query_id,
                    "query_name": query_name,
                    "webhook_url": query["discord_webhook_url"],
                    "channel_id": query.get("discord_channel_id", ""),
                    "embed_color": query["embed_color"],
                })
            
            total_new += len(new_items)
            total_all += len(items)
            
        except Exception as e:
            logger.error(f"Błąd [{query_name}] URL: {url[:50]}... : {e}", exc_info=True)
            db.add_log("ERROR", "scraper", f"Błąd [{query_name}] URL {url[:50]}: {str(e)}")
    
    return (query_name, total_new, total_all, all_results)
