# Vinted-Notification

> Real-time notification system for Vinted listings. Works across **all Vinted country domains** (pl, de, fr, it, es, nl...). Get instant Discord alerts when items matching your search criteria are posted — be the best buyer on the platform.

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20Raspberry%20Pi-green)
![Discord](https://img.shields.io/badge/Discord-Webhook-7289da)

---

## Features

- **Multi-domain** — Monitor vinted.pl, vinted.de, vinted.fr, vinted.it, vinted.es and 20+ other EU markets
- **Discord channel per topic** — Each search has its own webhook → channel (e.g. `#Stone Island 200`)
- **Rich embeds** — Up to 3 photos, price, condition, brand, size, seller rating, action links
- **Web panel** (port 8080) — Manage queries, view items, live logs
- **Anti-ban** — Session rotation, UA pool, rate limiting, jitter
- **Proxy support** — Optional proxy list for IP protection
- **Fast delivery** — 0.2s queue processing for real-time alerts

---

## Quick Start

### Windows / Linux / Mac

```bash
cd Vinted-pacz  # or Vinted-Notification
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
copy .env.example .env  # Windows
# cp .env.example .env  # Linux/Mac
python main.py
```

Open **http://localhost:8080** to manage queries.

### Raspberry Pi 3B (DietPi OS)

**Szczegółowy przewodnik:** [INSTALL_RPI.md](INSTALL_RPI.md)

**Szybka instalacja:**

```bash
cd ~/vinted-notification
bash deploy/install_rpi.sh
sudo systemctl start vinted-notification
```

Panel: `http://<IP_RASPBERRY_PI>:8080`

---

## How to Add a Query (Discord Channel → Vinted URL)

**Example:** Channel `#Stone Island 200` with search link:

```
https://www.vinted.pl/catalog?search_text=stone%20island%20&search_id=31370955643&order=newest_first
```

1. Go to Vinted (any domain: .pl, .de, .fr...)
2. Set your filters (search text, brand, price, size, etc.)
3. Copy the URL from the address bar
4. In the panel: **Queries** → **Add query**
5. Fill in:
   - **Name:** e.g. `Stone Island 200`
   - **URL:** Paste the Vinted URL
   - **Discord Webhook URL:** Create webhook for your channel (Channel Settings → Integrations → Webhooks)
   - **Channel name:** e.g. `Stone Island 200` (displayed in embed footer)

Each Discord channel = one webhook = one query. Example setup:

| Channel       | Webhook   | Vinted URL                          |
|---------------|-----------|-------------------------------------|
| #Stone Island 200 | webhook_A | vinted.pl/catalog?search_text=stone%20island&price_to=200 |
| #Nike Dresy   | webhook_B | vinted.pl/catalog?brand_ids[]=53&catalog[]=76 |
| #Carhartt DE  | webhook_C | vinted.de/catalog?search_text=carhartt |

---

## Creating a Discord Webhook

1. Discord → Server → Target channel
2. **Channel Settings** (gear) → **Integrations** → **Webhooks**
3. **Create Webhook** → Name (e.g. `Vinted-Notification`)
4. **Copy Webhook URL**
5. Paste into the panel

---

## Example Vinted URLs

| Description              | URL |
|--------------------------|-----|
| Stone Island, max 200 PLN | `https://www.vinted.pl/catalog?search_text=stone%20island&order=newest_first&price_to=200` |
| Carhartt jackets (DE)    | `https://www.vinted.de/catalog?search_text=carhartt&catalog[]=4&price_to=50` |
| Nike size M              | `https://www.vinted.pl/catalog?brand_ids[]=53&size_ids[]=207` |
| Arc'teryx search         | `https://www.vinted.fr/catalog?search_text=arcteryx&price_to=100` |

Parameters `time`, `search_id`, `page` are automatically stripped.

---

## Web Panel Tabs

| Tab        | Description                          |
|------------|--------------------------------------|
| Dashboard  | Stats, recent items, logs             |
| Queries    | Add/edit/delete/toggle queries        |
| Items      | All found listings with filters      |
| Logs       | Live logs with level filter          |
| Settings   | Scan interval, items per query, proxy |

---

## Settings

| Parameter              | Default | Description |
|-----------------------|---------|-------------|
| Scan interval         | 60s     | How often to check Vinted (min 10s) |
| Items per query       | 20      | Items to fetch per search (5–50)     |
| New item window       | 5 min   | Ignore items older than X minutes    |
| Query delay           | 5s      | Delay between queries (anti-ban)    |

**Warning:** Very short intervals (< 30s) may trigger IP blocking by Vinted. Use proxy if needed.

---

## Project Structure

```
Vinted-Notification/
├── main.py              # Entry point (3 threads: WebPanel, Scraper, Sender)
├── requirements.txt
├── .env.example
│
├── src/
│   ├── config.py        # Vinted domains, URL helpers
│   ├── core.py          # Scraping logic, queue processing
│   ├── database.py      # SQLite (queries, items, logs)
│   ├── discord_sender.py
│   ├── anti_ban.py      # Session rotation, rate limiting
│   ├── proxy_manager.py
│   ├── logger.py
│   └── pyVinted/        # Vinted API wrapper
│
├── web_panel/
│   ├── app.py           # Flask (port 8080)
│   └── templates/
│
└── data/
    └── vinted_notification.db
```

---

## Supported Vinted Domains

pl, de, fr, it, es, nl, be, at, cz, sk, hu, ro, se, fi, dk, no, pt, lt, lv, ee, hr, si, lu, gr, com

---

## Troubleshooting

**No Discord messages**
- Check Logs tab
- Test webhook: Queries → Test button
- Ensure webhook URL starts with `https://discord.com/api/webhooks/`

**401/403 from Vinted**
- Bot auto-refreshes cookies; if persistent, try proxy
- Check network access: `curl -I https://www.vinted.pl`

**ModuleNotFoundError**
```bash
pip install -r requirements.txt
```

---

## License

MIT — use, modify, distribute freely.
