"""
debug_api.py - Diagnostyka API Vinted + test wysylki Discord.
Uruchom: python debug_api.py
"""
import sys, json, sqlite3, os
sys.path.insert(0, '.')

print("=" * 60)
print("  VintedWatch — Diagnostyka v2")
print("=" * 60)

import requests
from urllib.parse import urlencode

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Referer": "https://www.vinted.pl/",
})

# KROK 1: Cookies
print("\n[1] Pobieranie cookies...")
r = session.get("https://www.vinted.pl/", timeout=15)
print(f"    Status: {r.status_code}, Cookies: {len(session.cookies)} szt.")

BASE = "https://www.vinted.pl/api/v2/catalog/items"

# KROK 2: Test bez order
print("\n[2] catalog/items BEZ parametru order (Carhartt 362)...")
params = [("brand_ids[]", "362"), ("per_page", "5")]
r = session.get(BASE, params=params, timeout=15)
print(f"    Status: {r.status_code}")
if r.status_code == 200:
    items = r.json().get("items", [])
    print(f"    Wynik: {len(items)} przedmiotow")
    for it in items[:2]:
        print(f"      - {it.get('title')} | {it.get('price',{}).get('amount')} PLN")

# KROK 3: Test z order=newest_first
print("\n[3] catalog/items Z order=newest_first...")
params = [("brand_ids[]", "362"), ("per_page", "5"), ("order", "newest_first")]
r = session.get(BASE, params=params, timeout=15)
print(f"    Status: {r.status_code}")
if r.status_code == 200:
    items = r.json().get("items", [])
    print(f"    Wynik: {len(items)} przedmiotow")
else:
    print(f"    Odpowiedz: {r.text[:200]}")

# KROK 4: Test z dwoma brand_ids
print("\n[4] catalog/items — Carhartt + Carhartt WIP (362 + 872289)...")
params = [("brand_ids[]", "362"), ("brand_ids[]", "872289"), ("per_page", "5")]
r = session.get(BASE, params=params, timeout=15)
print(f"    Status: {r.status_code}")
if r.status_code == 200:
    items = r.json().get("items", [])
    print(f"    Wynik: {len(items)} przedmiotow")
    for it in items[:2]:
        print(f"      - {it.get('title')} | {it.get('price',{}).get('amount')} PLN")

# KROK 5: Sprawdz query z bazy danych
print("\n[5] Sprawdzam zapytania z bazy danych...")
db_path = os.path.join("data", "vinted_watch.db")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    queries = conn.execute("SELECT id, name, url FROM queries WHERE active=1").fetchall()
    print(f"    Aktywnych zapytan: {len(queries)}")
    for q in queries:
        print(f"\n    [{q['id']}] {q['name']}")
        print(f"    URL: {q['url']}")
        
        # Testuj ten konkretny URL
        from urllib.parse import urlparse, parse_qsl
        parsed = urlparse(q['url'])
        url_params = parse_qsl(parsed.query)
        print(f"    Parametry URL: {url_params}")
        
        # Zbuduj params do API (tak jak robi bot)
        api_params = []
        for k, v in url_params:
            if k in ('time', 'search_id', 'page', 'order', 'disabled_personalization'):
                continue
            api_params.append((k, v))
        api_params.append(("per_page", "5"))
        api_params.append(("order", "newest_first"))
        
        print(f"    API params: {api_params}")
        r2 = session.get(BASE, params=api_params, timeout=15)
        print(f"    Status: {r2.status_code}")
        if r2.status_code == 200:
            items = r2.json().get("items", [])
            print(f"    >>> Wynik: {len(items)} przedmiotow <<<")
            for it in items[:2]:
                print(f"        - {it.get('title')} | {it.get('price',{}).get('amount')} PLN")
        else:
            print(f"    Odpowiedz: {r2.text[:300]}")
    conn.close()
else:
    print("    Brak bazy danych!")

# KROK 6: Test webhooka Discord
print("\n[6] Test webhooka Discord...")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    queries = conn.execute("SELECT name, discord_webhook_url FROM queries LIMIT 1").fetchall()
    conn.close()
    if queries:
        wh = queries[0]['discord_webhook_url']
        name = queries[0]['name']
        print(f"    Webhook dla: {name}")
        print(f"    URL: {wh[:60]}...")
        try:
            payload = {"embeds": [{"description": "Test diagnostyczny VintedWatch", "color": 5763719}]}
            r3 = requests.post(wh, json=payload, timeout=10)
            print(f"    Status: {r3.status_code} ({'OK - sprawdz Discord!' if r3.status_code == 204 else 'BLAD'})")
            if r3.status_code != 204:
                print(f"    Tresc: {r3.text[:200]}")
        except Exception as e:
            print(f"    BLAD: {e}")

print("\n" + "=" * 60)
print("Skopiuj i wyslij mi caly ten output!")
print("=" * 60)
