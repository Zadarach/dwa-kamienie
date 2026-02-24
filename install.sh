#!/bin/bash
# install.sh - Automatyczna instalacja Vinted Bot na Raspberry Pi / DietPi
# Wersja: 3.1

echo "🚀 Instalacja Vinted-Notification v3.1..."

# Sprawdź czy Python3 jest zainstalowany
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 nie znaleziony! Instaluję..."
    sudo apt update && sudo apt install -y python3 python3-pip python3-venv
fi

# Utwórz środowisko wirtualne
echo "📦 Tworzę środowisko wirtualne..."
python3 -m venv venv

# Aktywuj i zainstaluj zależności
echo "📥 Instaluję zależności..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Ustaw uprawnienia
echo "🔧 Ustawiam uprawnienia..."
chmod 777 data/
chmod 666 data/* 2>/dev/null

echo "✅ Instalacja zakończona!"
echo ""
echo "📌 Aby uruchomić bota:"
echo "   cd /root/vinted-bot"
echo "   source venv/bin/activate"
echo "   screen -S vinted-bot"
echo "   python3 main.py"
echo ""
echo "   (Ctrl+A, potem D aby odłączyć od screen)"