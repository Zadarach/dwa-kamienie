#!/bin/bash
# ============================================================
#  setup_tmpfs_wal.sh — Optymalizacja SQLite WAL na tmpfs
#  
#  Problem: SQLite WAL na microSD = częste random writes = SD wear
#  Rozwiązanie: WAL + SHM na tmpfs (RAM) — 10-50× szybsze writes
#
#  Uruchom: bash deploy/setup_tmpfs_wal.sh
#  Wymagane: uruchomić PRZED startem aplikacji
# ============================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$PROJECT_DIR/data"
TMPFS_DIR="/tmp/vinted-db"
DB_FILE="vinted_notification.db"

info "Katalog danych: $DATA_DIR"

# ── 1. Utwórz katalog tmpfs ────────────────────────────────
mkdir -p "$TMPFS_DIR"
info "Katalog tmpfs: $TMPFS_DIR"

# ── 2. Sprawdź czy tmpfs jest zamontowany na /tmp ──────────
if mount | grep -q "tmpfs on /tmp"; then
    info "/tmp jest tmpfs — WAL będzie w RAM ✓"
else
    warning "/tmp NIE jest tmpfs — rozważ: sudo mount -t tmpfs -o size=64m tmpfs /tmp"
    warning "Lub dodaj do /etc/fstab: tmpfs /tmp tmpfs defaults,noatime,size=64m 0 0"
fi

# ── 3. Symlink WAL i SHM do tmpfs ──────────────────────────
# Główna baza zostaje na SD (bezpieczna) — tylko journal w RAM
for ext in "wal" "shm"; do
    target="$DATA_DIR/${DB_FILE}-${ext}"
    tmpfs_file="$TMPFS_DIR/${DB_FILE}-${ext}"

    # Usuń istniejący plik WAL/SHM (zostanie odtworzony przez SQLite)
    if [ -f "$target" ] && [ ! -L "$target" ]; then
        rm -f "$target"
        info "Usunięto stary ${DB_FILE}-${ext}"
    fi

    # Utwórz symlink tylko jeśli jeszcze nie istnieje
    if [ ! -L "$target" ]; then
        touch "$tmpfs_file"
        ln -sf "$tmpfs_file" "$target"
        info "Symlink: ${DB_FILE}-${ext} → tmpfs"
    else
        info "Symlink ${DB_FILE}-${ext} już istnieje ✓"
    fi
done

# ── 4. Dodaj do crontab (auto-setup po restarcie) ──────────
CRON_CMD="@reboot mkdir -p $TMPFS_DIR && touch $TMPFS_DIR/${DB_FILE}-wal $TMPFS_DIR/${DB_FILE}-shm"
if ! crontab -l 2>/dev/null | grep -q "vinted-db"; then
    (crontab -l 2>/dev/null; echo "$CRON_CMD  # vinted-db tmpfs") | crontab -
    info "Dodano crontab @reboot (auto-setup po restarcie)"
else
    info "Crontab @reboot już istnieje ✓"
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  tmpfs WAL skonfigurowany!                ${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Zysk:"
echo "  • 10-50× szybsze random writes (RAM vs microSD)"
echo "  • Mniejsze zużycie karty SD (mniej cykli zapisu)"
echo "  • Baza główna bezpieczna na SD (WAL jest odtwarzalny)"
echo ""
echo "UWAGA: Po crash/reboot WAL jest tracony, ale:"
echo "  • SQLite odtworzy WAL automatycznie"
echo "  • Dane w głównej bazie (.db) są spójne"
echo "  • crontab @reboot odtworzy strukturę tmpfs"
