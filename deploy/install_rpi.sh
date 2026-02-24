#!/bin/bash
# ============================================================
#  Vinted-Notification — Skrypt instalacyjny dla Raspberry Pi 3b
#  System: DietPi / Raspberry Pi OS Lite
#  Uruchom: bash deploy/install_rpi.sh
# ============================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
info "Katalog projektu: $PROJECT_DIR"

# ── 1. Sprawdź Pythona ──────────────────────────────────────
info "Sprawdzam Python…"
PYTHON=$(command -v python3.11 || command -v python3.10 || command -v python3.9 || command -v python3)
[ -z "$PYTHON" ] && error "Python 3.9+ nie znaleziony"
PY_VERSION=$($PYTHON --version 2>&1)
info "Znaleziono: $PY_VERSION"

# ── 2. Zaktualizuj system ───────────────────────────────────
info "Aktualizacja pakietów systemu…"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip git

# ── 3. Wirtualne środowisko ─────────────────────────────────
VENV="$PROJECT_DIR/venv"
if [ ! -d "$VENV" ]; then
    info "Tworzę środowisko wirtualne…"
    $PYTHON -m venv "$VENV"
fi

info "Instaluję zależności Python…"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$PROJECT_DIR/requirements.txt" -q
info "Zależności zainstalowane"

# ── 4. Utwórz katalog danych ────────────────────────────────
mkdir -p "$PROJECT_DIR/data"
info "Katalog data/ gotowy"

# ── 5. Zainstaluj usługę systemd ────────────────────────────
CURRENT_USER=$(whoami)
SERVICE_FILE="$PROJECT_DIR/deploy/vinted-notification.service"
TARGET="/etc/systemd/system/vinted-notification.service"

info "Konfiguruję usługę systemd…"

# Podmień ścieżki i użytkownika w pliku service
sed "s|/home/dietpi/vinted-notification|$PROJECT_DIR|g; s|User=dietpi|User=$CURRENT_USER|g" \
    "$SERVICE_FILE" > /tmp/vinted-notification.service

sudo cp /tmp/vinted-notification.service "$TARGET"
sudo systemctl daemon-reload
sudo systemctl enable vinted-notification
info "Usługa systemd zainstalowana i włączona"

# ── 6. Optymalizacje RPi ────────────────────────────────────
info "Optymalizacje dla Raspberry Pi 3b…"

# Wyłącz swap jeśli masz ≥512MB RAM (redukuje zużycie karty SD)
if [ "$(free -m | awk '/^Mem:/{print $2}')" -gt 512 ]; then
    warning "Rozważ wyłączenie swap: sudo dphys-swapfile swapoff && sudo systemctl disable dphys-swapfile"
fi

# Zwiększ limit plików otwartych
if ! grep -q "vinted" /etc/security/limits.conf 2>/dev/null; then
    echo "$CURRENT_USER soft nofile 4096" | sudo tee -a /etc/security/limits.conf > /dev/null
    echo "$CURRENT_USER hard nofile 8192" | sudo tee -a /etc/security/limits.conf > /dev/null
fi

# tmpfs WAL — SQLite journal w RAM zamiast na karcie SD
info "Konfiguracja tmpfs WAL (ochrona karty SD)…"
bash "$PROJECT_DIR/deploy/setup_tmpfs_wal.sh"

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Vinted-Notification zainstalowany!       ${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Komendy:"
echo "  Uruchom:     sudo systemctl start vinted-notification"
echo "  Zatrzymaj:   sudo systemctl stop vinted-notification"
echo "  Status:      sudo systemctl status vinted-notification"
echo "  Logi live:   sudo journalctl -u vinted-notification -f"
echo "  Panel web:   http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo "Aby uruchomić teraz:"
echo "  sudo systemctl start vinted-notification"
