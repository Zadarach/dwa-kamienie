# Instalacja Vinted-Notification na Raspberry Pi 3B (DietPi OS)

Szczegółowy przewodnik instalacji krok po kroku dla Raspberry Pi 3B z DietPi OS.

---

## Wymagania

- **Raspberry Pi 3B** (1GB RAM)
- **DietPi OS** (lub Raspberry Pi OS Lite)
- **Połączenie internetowe** (WiFi lub Ethernet)
- **Dostęp SSH** do Raspberry Pi

---

## Krok 1: Przygotowanie DietPi

### 1.1. Zaloguj się na Raspberry Pi

```bash
ssh dietpi@<IP_RASPBERRY_PI>
# lub
ssh dietpi@raspberrypi.local
```

### 1.2. Zaktualizuj system

```bash
sudo apt-get update
sudo apt-get upgrade -y
```

### 1.3. Sprawdź Python

DietPi zazwyczaj ma Python 3.9+. Sprawdź:

```bash
python3 --version
# Powinno pokazać: Python 3.9.x lub nowszy
```

Jeśli nie masz Python 3.9+:

```bash
sudo apt-get install -y python3 python3-pip python3-venv
```

---

## Krok 2: Pobranie projektu

### 2.1. Przejdź do katalogu domowego

```bash
cd ~
```

### 2.2. Sklonuj repozytorium (lub wgraj pliki)

**Opcja A: Git (jeśli masz repozytorium)**

```bash
git clone <URL_REPOZYTORIUM> vinted-notification
cd vinted-notification
```

**Opcja B: Wgranie plików przez SCP (z Windows)**

Na komputerze Windows:

```powershell
scp -r C:\Users\lukasz\Desktop\Vinted-pacz dietpi@<IP_RPI>:~/vinted-notification
```

Następnie na Raspberry Pi:

```bash
cd ~/vinted-notification
```

---

## Krok 3: Instalacja automatyczna (zalecana)

### 3.1. Uruchom skrypt instalacyjny

```bash
cd ~/vinted-notification
chmod +x deploy/install_rpi.sh
bash deploy/install_rpi.sh
```

Skrypt automatycznie:
- Zainstaluje zależności Python
- Utworzy środowisko wirtualne
- Zainstaluje pakiety z `requirements.txt`
- Skonfiguruje usługę systemd
- Włączy auto-start po restarcie

### 3.2. Sprawdź instalację

```bash
# Sprawdź czy usługa istnieje
sudo systemctl status vinted-notification

# Sprawdź logi
sudo journalctl -u vinted-notification -n 50
```

---

## Krok 4: Instalacja ręczna (alternatywa)

Jeśli skrypt nie działa lub chcesz zrobić to ręcznie:

### 4.1. Utwórz środowisko wirtualne

```bash
cd ~/vinted-notification
python3 -m venv venv
source venv/bin/activate
```

### 4.2. Zainstaluj zależności

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4.3. Utwórz katalog danych

```bash
mkdir -p data
```

### 4.4. Skonfiguruj zmienne środowiskowe (opcjonalnie)

```bash
cp .env.example .env
nano .env
```

Zmień `FLASK_SECRET` na losowy ciąg znaków (np. wygeneruj: `openssl rand -hex 32`).

### 4.5. Zainstaluj usługę systemd

```bash
# Edytuj plik service i zmień ścieżki
nano deploy/vinted-notification.service

# Skopiuj do systemd
sudo cp deploy/vinted-notification.service /etc/systemd/system/

# Przeładuj systemd
sudo systemctl daemon-reload

# Włącz auto-start
sudo systemctl enable vinted-notification
```

---

## Krok 5: Uruchomienie

### 5.1. Uruchom usługę

```bash
sudo systemctl start vinted-notification
```

### 5.2. Sprawdź status

```bash
sudo systemctl status vinted-notification
```

Powinieneś zobaczyć:

```
● vinted-notification.service - Vinted-Notification
   Loaded: loaded (/etc/systemd/system/vinted-notification.service; enabled)
   Active: active (running) since ...
```

### 5.3. Sprawdź logi

```bash
# Ostatnie 50 linii
sudo journalctl -u vinted-notification -n 50

# Logi na żywo
sudo journalctl -u vinted-notification -f
```

Powinieneś zobaczyć:

```
Vinted-Notification v2.0 — uruchamianie
✅ Baza danych gotowa
📋 Zapytania: 0 total, 0 aktywnych
⚠️  Dodaj zapytania przez panel: http://localhost:8080
```

### 5.4. Znajdź IP Raspberry Pi

```bash
hostname -I
# Przykład: 192.168.1.100
```

---

## Krok 6: Dostęp do panelu webowego

### 6.1. Otwórz panel w przeglądarce

Na komputerze (lub telefonie w tej samej sieci):

```
http://<IP_RASPBERRY_PI>:8080
```

Przykład:
```
http://192.168.1.100:8080
```

### 6.2. Dodaj pierwsze zapytanie

1. **Vinted** → ustaw filtry → skopiuj URL
2. **Discord** → kanał → Ustawienia → Integracje → Webhooks → Utwórz → skopiuj URL
3. **Panel** → Zapytania → Nowe zapytanie → wklej URL-e → Zapisz

---

## Krok 7: Konfiguracja firewall (jeśli potrzebna)

Jeśli nie możesz dostać się do panelu z innego urządzenia:

```bash
# Sprawdź czy firewall jest aktywny
sudo ufw status

# Jeśli aktywny, otwórz port 8080
sudo ufw allow 8080/tcp
sudo ufw reload
```

---

## Zarządzanie usługą

### Podstawowe komendy

```bash
# Uruchom
sudo systemctl start vinted-notification

# Zatrzymaj
sudo systemctl stop vinted-notification

# Restart
sudo systemctl restart vinted-notification

# Status
sudo systemctl status vinted-notification

# Wyłącz auto-start
sudo systemctl disable vinted-notification

# Włącz auto-start
sudo systemctl enable vinted-notification
```

### Logi

```bash
# Ostatnie 100 linii
sudo journalctl -u vinted-notification -n 100

# Logi na żywo (Ctrl+C aby wyjść)
sudo journalctl -u vinted-notification -f

# Logi od dzisiaj
sudo journalctl -u vinted-notification --since today

# Logi z konkretnego dnia
sudo journalctl -u vinted-notification --since "2025-02-19" --until "2025-02-20"
```

---

## Aktualizacja projektu

### Automatyczna (skrypt)

```bash
cd ~/vinted-notification
bash deploy/update.sh
```

### Ręczna

```bash
cd ~/vinted-notification

# Zatrzymaj usługę
sudo systemctl stop vinted-notification

# Pobierz najnowsze zmiany (jeśli używasz git)
git pull

# Zaktualizuj zależności
source venv/bin/activate
pip install -r requirements.txt --upgrade

# Uruchom ponownie
sudo systemctl start vinted-notification
```

---

## Optymalizacje dla Raspberry Pi 3B

### 1. Wyłącz swap (jeśli masz ≥512MB RAM)

Swap na karcie SD jest wolny i zużywa ją. Jeśli masz wystarczająco RAM:

```bash
sudo dphys-swapfile swapoff
sudo systemctl disable dphys-swapfile
```

### 2. Zwiększ limit plików otwartych

```bash
echo "dietpi soft nofile 4096" | sudo tee -a /etc/security/limits.conf
echo "dietpi hard nofile 8192" | sudo tee -a /etc/security/limits.conf
```

Wymaga wylogowania i ponownego zalogowania.

### 3. Optymalizacja SQLite (już w kodzie)

Projekt używa:
- WAL mode (Write-Ahead Logging)
- Thread-local connections
- Cache 8MB w pamięci

### 4. Monitorowanie zasobów

```bash
# CPU i RAM
htop

# Dysk
df -h

# Pamięć
free -h
```

---

## Rozwiązywanie problemów

### Problem: Panel nie działa (błąd połączenia)

**Sprawdź:**

```bash
# Czy usługa działa?
sudo systemctl status vinted-notification

# Czy port 8080 jest otwarty?
sudo netstat -tlnp | grep 8080

# Czy firewall blokuje?
sudo ufw status
```

**Rozwiązanie:**

```bash
# Uruchom usługę
sudo systemctl start vinted-notification

# Otwórz port w firewall
sudo ufw allow 8080/tcp
```

---

### Problem: Błąd "ModuleNotFoundError"

**Rozwiązanie:**

```bash
cd ~/vinted-notification
source venv/bin/activate
pip install -r requirements.txt
```

---

### Problem: Błąd "database is locked"

**Rozwiązanie:**

Projekt używa WAL mode i thread-local connections — ten błąd nie powinien występować. Jeśli się pojawi:

```bash
# Zatrzymaj usługę
sudo systemctl stop vinted-notification

# Sprawdź czy proces nie działa
ps aux | grep python

# Uruchom ponownie
sudo systemctl start vinted-notification
```

---

### Problem: Vinted zwraca 401/403

**Rozwiązanie:**

Bot automatycznie odnawia cookies. Jeśli problem trwa:

1. Sprawdź logi: `sudo journalctl -u vinted-notification -f`
2. Sprawdź połączenie: `curl -I https://www.vinted.pl`
3. Rozważ użycie proxy (Panel → Ustawienia → Proxy)

---

### Problem: Wysokie zużycie CPU/RAM

**Sprawdź:**

```bash
htop
```

**Rozwiązanie:**

1. Zmniejsz `scan_interval` w Panel → Ustawienia (np. 90s zamiast 60s)
2. Zmniejsz `items_per_query` (np. 15 zamiast 20)
3. Wyłącz nieaktywne zapytania

---

### Problem: Brak powiadomień na Discord

**Sprawdź:**

1. Panel → Logi → czy są błędy
2. Panel → Zapytania → Test webhooka
3. Sprawdź URL webhooka w Discord (czy nie wygasł)

**Rozwiązanie:**

1. Utwórz nowy webhook w Discord
2. Zaktualizuj URL w Panel → Zapytania → Edytuj

---

## Backup bazy danych

### Ręczny backup

```bash
cd ~/vinted-notification
sudo systemctl stop vinted-notification
cp data/vinted_notification.db data/vinted_notification.db.backup
sudo systemctl start vinted-notification
```

### Automatyczny backup (cron)

```bash
crontab -e
```

Dodaj:

```cron
# Backup codziennie o 3:00
0 3 * * * cp /home/dietpi/vinted-notification/data/vinted_notification.db /home/dietpi/vinted-notification/data/vinted_notification.db.backup.$(date +\%Y\%m\%d)
```

---

## Odinstalowanie

```bash
# Zatrzymaj i wyłącz usługę
sudo systemctl stop vinted-notification
sudo systemctl disable vinted-notification

# Usuń plik service
sudo rm /etc/systemd/system/vinted-notification.service
sudo systemctl daemon-reload

# Usuń projekt (opcjonalnie)
rm -rf ~/vinted-notification
```

---

## Wsparcie

- **Logi:** `sudo journalctl -u vinted-notification -f`
- **Panel:** `http://<IP_RPI>:8080`
- **Status:** `sudo systemctl status vinted-notification`

---

**Gotowe!** Vinted-Notification działa na Raspberry Pi 3B z DietPi OS.
