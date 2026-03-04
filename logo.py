#!/usr/bin/env python3
"""
FULL AUTO FLASH TOOL – ORNO MD-1080 (v2.2)
Autor: Gemini & User
Proces: Konwersja -> Przerwanie Boota -> Transfer YMODEM -> Flashowanie -> Logowanie
"""

import os
import sys
import time
import glob
import shutil
import serial
import subprocess
from pathlib import Path

# --- KONFIGURACJA URZĄDZENIA ---
PARTITION_SIZE = 204800  # 200 KiB (dokładnie tyle ile ma partycja logo)
TARGET_RES = (1024, 600)
START_QUALITY = 85
MIN_QUALITY = 50
QUALITY_STEP = 5
BAUDRATE = 115200
LOG_FILE = "flash_log.txt"

# Adresy U-Boot
FLASH_ADDR = "0x23b000"
FLASH_SIZE = "0x32000"
LOAD_ADDR = "0x82000000"

def log(msg, to_file_only=False):
    """Zapisuje wiadomość do logu i opcjonalnie wyświetla na ekranie."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted + "\n")
    if not to_file_only:
        print(msg)

def check_dependencies():
    """Sprawdza czy niezbędne narzędzia systemowe są zainstalowane."""
    for tool in ["convert", "sb"]:
        if not shutil.which(tool):
            log(f"❌ BŁĄD: Brak narzędzia '{tool}'. Zainstaluj je: sudo apt install imagemagick lrzsz")
            sys.exit(1)

def prepare_image(input_path, output_path):
    """Konwertuje obraz i dopasowuje jakość do rozmiaru partycji."""
    quality = START_QUALITY
    while quality >= MIN_QUALITY:
        print(f"  > Próba konwersji (Jakość: {quality})...", end="\r")
        try:
            subprocess.run([
                "convert", str(input_path),
                "-resize", f"{TARGET_RES[0]}x{TARGET_RES[1]}",
                "-background", "black",
                "-gravity", "center",
                "-extent", f"{TARGET_RES[0]}x{TARGET_RES[1]}",
                "-strip", "-quality", str(quality),
                str(output_path)
            ], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            log(f"❌ BŁĄD ImageMagick: {e.stderr.decode()}")
            return False

        size = os.path.getsize(output_path)
        if size <= PARTITION_SIZE:
            log(f"\n  ✅ Obraz gotowy: {size} bajtów (limit: {PARTITION_SIZE}, jakość: {quality})")
            # Padding 0xFF do pełnego rozmiaru partycji
            with open(output_path, "ab") as f:
                f.write(b"\xFF" * (PARTITION_SIZE - size))
            return True
        quality -= QUALITY_STEP
    
    log("\n❌ BŁĄD: Obraz jest zbyt złożony, by zmieścić go w 200 KiB.")
    return False

def wait_for_uboot_and_interrupt(ser):
    """Czeka na sygnał z U-Boot i wysyła klawisz przerwania."""
    log("⏳ Czekam na U-Boot (zrestartuj teraz domofon)...")
    start_time = time.time()
    buffer = ""
    while (time.time() - start_time) < 30: # 30 sekund timeoutu
        if ser.in_waiting:
            chunk = ser.read(ser.in_waiting).decode(errors='ignore')
            buffer += chunk
            if "U-Boot" in buffer or "Hit any key" in buffer:
                log("🚀 Wykryto start! Przerywam autoboot...")
                for _ in range(15): # Seria enterów dla pewności
                    ser.write(b"\n")
                    time.sleep(0.05)
                return True
        time.sleep(0.1)
    return False

def main():
    if len(sys.argv) < 2:
        print("Użycie: python3 flash_logo_pro.py twoje_logo.jpg")
        sys.exit(1)

    # Inicjalizacja pliku logu
    with open(LOG_FILE, "w") as f: f.write("--- NOWA SESJA FLASHOWANIA ---\n")
    
    input_file = Path(sys.argv[1])
    output_bin = Path("temp_logo.bin")
    
    check_dependencies()
    
    log("--- ETAP 1: Przygotowanie obrazu ---")
    if not prepare_image(input_file, output_bin):
        sys.exit(1)

    # Detekcja portu
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    if not ports:
        log("❌ BŁĄD: Nie znaleziono portu szeregowego USB.")
        sys.exit(1)
    port = ports[0]

    log(f"--- ETAP 2: Połączenie ({port}) ---")
    try:
        ser = serial.Serial(port, BAUDRATE, timeout=1)
    except Exception as e:
        log(f"❌ BŁĄD: Nie można otworzyć portu {port}: {e}")
        sys.exit(1)

    if not wait_for_uboot_and_interrupt(ser):
        log("❌ BŁĄD: Timeout. Nie wykryto konsoli U-Boot.")
        sys.exit(1)

    # Przygotowanie U-Boot do YMODEM
    log("  > Wysyłam komendę loady...")
    ser.write(f"loady {LOAD_ADDR}\n".encode())
    time.sleep(1)
    
    # KLUCZOWE: Zamknięcie portu dla zewnętrznego procesu 'sb'
    ser.close()

    log("--- ETAP 3: Przesyłanie danych (YMODEM) ---")
    try:
        # Przekierowanie I/O bezpośrednio na port szeregowy
        cmd = f"sb --ymodem {output_bin} < {port} > {port}"
        subprocess.run(cmd, shell=True, check=True)
        log("  ✅ Transfer zakończony pomyślnie.")
    except subprocess.CalledProcessError:
        log("❌ BŁĄD: Błąd przesyłania przez 'sb'!")
        sys.exit(1)

    # Powrót do kontroli przez Pythona
    log("--- ETAP 4: Flashowanie ---")
    ser.open()
    time.sleep(1)

    flash_commands = [
        ("sf probe", "Inicjalizacja Flash"),
        (f"sf erase {FLASH_ADDR} +{FLASH_SIZE}", "Kasowanie partycji"),
        (f"sf write {LOAD_ADDR} {FLASH_ADDR} $filesize", "Zapisywanie nowego logo"),
        ("reset", "Restart urządzenia")
    ]

    for cmd, desc in flash_commands:
        log(f"  > {desc} ({cmd})...")
        ser.write(f"{cmd}\n".encode())
        time.sleep(1)
        # Odczyt odpowiedzi i zapis do logu
        if ser.in_waiting:
            resp = ser.read(ser.in_waiting).decode(errors='ignore')
            log(f"[U-BOOT RESP]: {resp.strip()}", to_file_only=True)
            if "fail" in resp.lower() or "error" in resp.lower():
                log(f"⚠️ OSTRZEŻENIE: U-Boot zgłosił błąd podczas: {cmd}")

    ser.close()
    log("\n✅ OPERACJA ZAKOŃCZONA SUKCESEM!")
    log(f"Szczegóły operacji znajdziesz w pliku {LOG_FILE}")

if __name__ == "__main__":
    main()