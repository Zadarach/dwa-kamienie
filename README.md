# Vinted-Notification v4.0

> Real-time notification system for Vinted listings. Works across **all Vinted country domains** (pl, de, fr, it, es, nl...). Get instant Discord alerts when items matching your search criteria are posted — be the best buyer on the platform.

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20Raspberry%20Pi-green)
![Discord](https://img.shields.io/badge/Discord-Webhook%20%2F%20Bot-7289da)

---

## 🔥 Nowości w wersji 4.0
- **Fast Scan Mode (5-8s)** — Błyskawiczne skanowanie oparte na `asyncio`, pozwalające wyłapać okazje w czasie rzeczywistym.
- **Seller Tracking** — Śledzenie konkretnych sprzedawców (po User ID) i natychmiastowe powiadomienia o ich nowych ogłoszeniach.
- **Price Drop Alerts** — Bot zapamiętuje przedmioty i informuje Cię, gdy sprzedawca obniży cenę (wylicza zaoszczędzoną kwotę i procent obniżki).
- **Multi-URL Queries** — Możliwość podpięcia wielu linków wyszukiwania pod jedno zapytanie (i jeden kanał Discord).
- **Advanced Anti-Ban (curl_cffi)** — Baza na TLS fingerprint imitującym prawdziwą przeglądarkę Chrome, co skutecznie omija zabezpieczenia Cloudflare.

## Features

- **Multi-domain** — Monitoruj vinted.pl, vinted.de, vinted.fr, vinted.it, vinted.es i ponad 20 innych rynków EU.
- **Discord channel per topic** — Każde wyszukiwanie ma własny webhook/kanał (np. `#Stone Island 200`).
- **Rich embeds** — Do 3 zdjęć, cena, stan, marka, rozmiar, ocena sprzedawcy i linki do akcji.
- **Web panel** (port 8080) — Wygodne zarządzanie zapytaniami, sprzedawcami i podgląd na żywo.
- **Anti-ban** — Rotacja sesji, User-Agent, rate limiting, jitter. Obsługa proxy oraz Cloudflare WARP.

---

## Quick Start

### Windows / Linux / Mac

```bash
git clone [https://github.com/Zadarach/dwa-kamienie.git](https://github.com/Zadarach/dwa-kamienie.git)
cd dwa-kamienie
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env  # Skopiuj i uzupełnij zmienne (jeśli używasz)
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
├── main.py                  # Entry point (asyncio: Scraper, Sender, WebPanel)
├── requirements.txt         # Zależności Python
├── .env.example             # Przykład zmiennych środowiskowych
├── .gitignore               # Ignorowane pliki
├── README.md                # Dokumentacja projektu (v4.0)
├── INSTALL_RPI.md           # Instrukcja instalacji na Raspberry Pi
│
├── install_warp.sh          # Skrypt instalacji Cloudflare WARP (ochrona IP)
├── optimize_rpi.sh          # Skrypt optymalizacji pod 1GB RAM (RPi)
│
├── deploy/                  # Pliki wdrożeniowe (systemd)
│   ├── vinted-bot.service   # Usługa systemd (autostart bota)
│   └── install_systemd.sh   # Skrypt instalacji usługi systemd
│
├── src/                     # Kod źródłowy Python
│   ├── config.py            # Domeny Vinted, helpery URL
│   ├── core.py              # Logika scrapingu, kolejka, seller tracking, price drop
│   ├── database.py          # Baza danych SQLite (v4.0)
│   ├── discord_sender.py    # Wysyłka embedów na Discord
│   ├── discord_bot.py       # Obsługa Discord Bot API
│   ├── anti_ban.py          # Zabezpieczenia przed banem IP (curl_cffi)
│   ├── proxy_manager.py     # Zarządzanie proxy / WARP
│   ├── logger.py            # System logowania
│   └── pyVinted/            # Wrapper API Vinted
│
├── web_panel/               # Panel webowy Flask (port 8080)
│   ├── app.py               # Routy, formularze, API
│   ├── templates/           # Szablony HTML (dashboard, queries, sellers, itp.)
│   └── static/              # Pliki statyczne (CSS, JS, img)
│
└── data/                    # Baza danych i logi (ignorowane przez git)
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
