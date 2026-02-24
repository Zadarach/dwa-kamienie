#!/bin/bash
# install_systemd.sh - Instalacja usługi systemd dla Vinted Bot
# Wersja: 1.0

echo "🚀 Instalacja usługi systemd dla Vinted Bot..."

BOT_DIR="/root/vinted-bot"
SERVICE_FILE="/etc/systemd/system/vinted-bot.service"
TEMPLATE_FILE="$BOT_DIR/deploy/vinted-bot.service"

if [ "$EUID" -ne 0 ]; then
    echo "❌ Uruchom jako root (sudo ./install_systemd.sh)"
    exit 1
fi

if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "❌ Nie znaleziono pliku szablonu: $TEMPLATE_FILE"
    exit 1
fi

if [ ! -d "$BOT_DIR/venv" ]; then
    echo "❌ Nie znaleziono środowiska wirtualnego: $BOT_DIR/venv"
    echo "Najpierw uruchom: ./install.sh"
    exit 1
fi

echo "📦 Kopiowanie pliku usługi..."
cp "$TEMPLATE_FILE" "$SERVICE_FILE"

echo "🔄 Przeładowywanie systemd..."
systemctl daemon-reload

echo "▶ Włączanie autostartu..."
systemctl enable vinted-bot

echo "✅ Uruchamianie usługi..."
systemctl start vinted-bot

sleep 2
systemctl status vinted-bot --no-pager

echo ""
echo "✅ Usługa systemd zainstalowana!"
echo ""
echo "📌 Przydatne komendy:"
echo "   systemctl status vinted-bot     - Status usługi"
echo "   systemctl stop vinted-bot       - Zatrzymaj bota"
echo "   systemctl start vinted-bot      - Uruchom bota"
echo "   systemctl restart vinted-bot    - Restart bota"
echo "   journalctl -u vinted-bot -f     - Podgląd logów na żywo"