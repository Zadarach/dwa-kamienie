#!/bin/bash
# Vinted-Notification — skrypt aktualizacji
# Uruchom: bash deploy/update.sh
set -e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "[INFO] Zatrzymuję usługę…"
sudo systemctl stop vinted-notification 2>/dev/null || true

echo "[INFO] Aktualizuję zależności…"
"$PROJECT_DIR/venv/bin/pip" install -r requirements.txt -q

echo "[INFO] Uruchamiam usługę…"
sudo systemctl start vinted-notification

echo "[OK] Aktualizacja zakończona"
echo "Logi: sudo journalctl -u vinted-notification -f"
