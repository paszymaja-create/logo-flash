#!/usr/bin/env python3
"""
ORNO MD-1080 Logo Flasher
Wersja: 1.4.1
Data: 2026-03-07

Zmiany w tej wersji:
• Stabilne wywołanie sb (port zamykany przed transferem)
• Sprawdzenie Baseline JPEG po konwersji
• Zawsze pełny zapis partycji (0x32000)
• Diagnostyka odpowiedzi U-Boot + wykrywanie błędów
• Zwiększone timeouty i flush
• Lepsze logowanie rozmiaru przed/po padding
• Automatyczne numerowanie wersji dla drobnych poprawek
"""

import os, sys, time, glob, shutil, serial, subprocess
from pathlib import Path

# --- KONFIGURACJA URZĄDZENIA (ORNO MD-1080) ---
PARTITION_SIZE = 204800     # 200 KiB - całkowity rozmiar flash
IMAGE_LIMIT_KB = 163840     # 160 KiB - limit samej grafiki
TARGET_RES = (1024, 600)    # Natywna rozdzielczość ekranu
BAUDRATE = 115200
LOG_FILE = "flash_log.txt"

# Adresacja w pamięci Flash
FLASH_ADDR = "0x23b000"
FLASH_SIZE = "0x32000"
LOAD_ADDR = "0x82000000"

# --- FUNKCJE POMOCNICZE ---

def log(msg):
    ts = time.strftime("%H:%M:%S")
    with open(LOG_FILE, "a") as f: f.write(f"[{ts}] {msg}\n")
    print(msg)

def find_latest_image():
    valid_exts = ('*.jpg', '*.jpeg', '*.png', '*.bmp')
    files = []
    for ext in valid_exts:
        files.extend(glob.glob(ext))
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return Path(files[0])

def is_baseline_jpeg(file_path):
    try:
        output = subprocess.check_output(["identify", "-verbose", str(file_path)], text=True)
        for line in output.splitlines():
            if "Interlace" in line:
                return "None" in line
        return True
    except Exception as e:
        log(f"❌ Nie udało się sprawdzić typu JPEG: {e}")
        return False

def prepare_image(input_path, output_path):
    quality = 85
    while quality >= 35:
        cmd = [
            "convert", str(input_path),
            "-resize", f"{TARGET_RES[0]}x{TARGET_RES[1]}^",
            "-gravity", "center",
            "-extent", f"{TARGET_RES[0]}x{TARGET_RES[1]}",
            "-strip",
            "-interlace", "none",
            "-sampling-factor", "4:2:0",
            "-quality", str(quality),
            "-define", "jpeg:optimize-coding=true",
            str(output_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        baseline = is_baseline_jpeg(output_path)
        size = os.path.getsize(output_path)

        if baseline and size <= IMAGE_LIMIT_KB:
            log(f"✅ Obraz gotowy: {size:,} B, Baseline JPEG, quality={quality}%")
            if size < PARTITION_SIZE:
                with open(output_path, "ab") as f:
                    f.write(b"\xFF" * (PARTITION_SIZE - size))
            return True

        log(f"Próba quality={quality}% → {'Progressive' if not baseline else 'za duży'} ({size:,} B)")
        quality -= 3

    log("❌ Nie udało się przygotować obraz w limicie i Baseline JPEG.")
    return False

def read_response(ser, max_time=4.0, cmd_name=""):
    response = ""
    start = time.time()
    while time.time() - start < max_time:
        if ser.in_waiting > 0:
            chunk = ser.read(ser.in_waiting).decode('ascii', errors='replace')
            response += chunk
            print(chunk, end='', flush=True)
        time.sleep(0.05)
    if response:
        log(f"Odpowiedź na '{cmd_name}':\n{response.strip()[:400]}")
    return response

# --- GŁÓWNY SKRYPT ---

def main():
    # Sprawdzenie narzędzi
    for tool in ["convert", "identify", "sb"]:
        if not shutil.which(tool):
            print(f"Błąd: Brak narzędzia '{tool}'. Zainstaluj: sudo apt install imagemagick lrzsz")
            sys.exit(1)

    # Znalezienie obrazu
    img_path = find_latest_image()
    if not img_path:
        log("❌ Nie znaleziono pliku graficznego w bieżącym folderze!")
        sys.exit(1)

    log(f"Wybrano najnowszy plik: {img_path}")
    out_bin = Path("logo_final.bin")

    if not prepare_image(img_path, out_bin):
        sys.exit(1)

    # Port UART
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    if not ports:
        log("❌ Nie znaleziono portu UART (/dev/ttyUSB* lub /dev/ttyACM*)")
        sys.exit(1)

    port = ports[0]
    log(f"Używam portu: {port}")

    try:
        ser = serial.Serial(port, BAUDRATE, timeout=0.4)

        log("Czekam na U-Boot... Włącz zasilanie domofonu teraz")
        detected = False
        start_time = time.time()

        while time.time() - start_time < 45:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting).decode('ascii', errors='replace')
                print(data, end='', flush=True)
                if "U-Boot" in data or "Hit any key" in data:
                    log("\n→ Wykryto U-Boot – przerywanie autoboot...")
                    for _ in range(8):
                        ser.write(b"\r\n")
                        time.sleep(0.04)
                    detected = True
                    break
            time.sleep(0.08)

        if not detected:
            log("❌ Timeout – brak sygnału U-Boot")
            sys.exit(1)

        # YMODEM – sb po zamknięciu portu
        ser.flush()
        ser.close()
        time.sleep(0.4)

        log("→ Uruchamiam sb (YMODEM)...")
        try:
            result = subprocess.run(
                ["sb", "--ymodem", str(out_bin)],
                stdin=open(port, "rb"),
                stdout=open(port, "wb"),
                stderr=subprocess.PIPE,
                text=True,
                timeout=90,
                check=True
            )
            log("→ sb zakończone sukcesem")
        except subprocess.TimeoutExpired:
            log("❌ sb: timeout po 90 sekundach")
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            err = e.stderr.strip() if e.stderr else ""
            log(f"❌ sb zwróciło błąd (kod {e.returncode}): {err}")
            sys.exit(1)
        except FileNotFoundError:
            log("❌ sb nie znaleziono – zainstaluj lrzsz")
            sys.exit(1)

        # Ponownie otwieramy port
        time.sleep(0.6)
        ser.open()
        time.sleep(0.8)

        # Flashowanie
        log("\nZapis do SPI Flash...")
        time.sleep(0.8)

        commands = [
            ("sf probe", 4.0),
            (f"sf erase {FLASH_ADDR} +{FLASH_SIZE}", 8.0),
            (f"sf write {LOAD_ADDR} {FLASH_ADDR} 0x{PARTITION_SIZE:x}", 6.0),
            ("reset", 2.0)
        ]

        for cmd, wait_time in commands:
            log(f"Wysyłam: {cmd}")
            ser.write(f"{cmd}\r\n".encode())
            time.sleep(0.4)
            resp = read_response(ser, wait_time, cmd)
            if any(err in resp.lower() for err in ["error", "bad", "fail", "not found", "unknown"]):
                log(f"!!! Prawdopodobny błąd przy komendzie: {cmd}")
                if "reset" not in cmd:
                    log("Przerwanie – dalsze komendy mogą być niebezpieczne")
                    sys.exit(1)

        log("\n✨ Operacja zakończona – czekam na restart urządzenia...")

    except serial.SerialException as e:
        log(f"❌ Problem z portem szeregowym: {e}")
        sys.exit(1)
    except Exception as e:
        log(f"❌ Nieoczekiwany błąd: {type(e).__name__}: {e}")
        sys.exit(1)
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    main()