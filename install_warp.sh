#!/bin/bash
# install_warp.sh - Instalacja Cloudflare WARP na Raspberry Pi / DietPi
# Wersja: 1.0

echo "🚀 Instalacja Cloudflare WARP..."

# Sprawdź architekturę
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    echo "✅ Wykryto ARM64 (Raspberry Pi)"
    REPO_ARCH="arm64"
elif [ "$ARCH" = "x86_64" ]; then
    echo "✅ Wykryto x86_64"
    REPO_ARCH="amd64"
else
    echo "❌ Nieobsługiwana architektura: $ARCH"
    exit 1
fi

# Dodaj repozytorium Cloudflare
echo "📦 Dodawanie repozytorium Cloudflare..."
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | sudo gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg

echo "deb [arch=$REPO_ARCH signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] http://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflare-client.list

# Aktualizuj i zainstaluj
echo "📥 Instalacja pakietów..."
sudo apt-get update
sudo apt-get install -y cloudflare-warp

# Rejestracja WARP (automatyczna)
echo "🔐 Rejestracja WARP..."
sudo warp-cli registration new

# Połącz z WARP
echo "🌐 Łączenie z Cloudflare WARP..."
sudo warp-cli connect

# Ustaw tryb persistent
sudo warp-cli set-mode proxy
sudo warp-cli set-proxy-port 40000

echo ""
echo "✅ Cloudflare WARP zainstalowany i połączony!"
echo ""
echo "📌 Przydatne komendy:"
echo "   warp-cli status          - Sprawdź status połączenia"
echo "   warp-cli disconnect      - Rozłącz WARP"
echo "   warp-cli connect         - Połącz WARP"
echo "   warp-cli registration delete - Wyrejestruj urządzenie"
echo ""
echo "🔧 Aby bot używał WARP, ustaw proxy na: socks5://127.0.0.1:40000"