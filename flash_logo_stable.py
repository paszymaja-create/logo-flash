#!/usr/bin/env python3
"""
STABLE AUTO FLASH – ORNO MD-1080
Bez konfliktu portu z sb.
"""

import os
import sys
import time
import glob
import shutil
import serial
import subprocess
from pathlib import Path

# --- KONFIG ---
PARTITION_SIZE = 204800
TARGET_RES = (1024, 600)
BAUDRATE = 115200
LOAD_ADDR = "0x82000000"
FLASH_ADDR = "0x23b000"
FLASH_SIZE = "0x32000"

START_QUALITY = 85
MIN_QUALITY = 60
QUALITY_STEP = 5


# ------------------------------------------------------------
# DEPENDENCIES
# ------------------------------------------------------------

def check_dependencies():
    for tool in ["convert", "sb"]:
        if not shutil.which(tool):
            print(f"Brak narzędzia: {tool}")
            sys.exit(1)


# ------------------------------------------------------------
# SERIAL
# ------------------------------------------------------------

def detect_port():
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    if not ports:
        print("Nie znaleziono portu USB.")
        sys.exit(1)
    print(f"Używam portu: {ports[0]}")
    return ports[0]


def wait_for(ser, text, timeout=5):
    end = time.time() + timeout
    buffer = b""

    while time.time() < end:
        if ser.in_waiting:
            buffer += ser.read(ser.in_waiting)
            if text.encode() in buffer:
                return True
        time.sleep(0.05)
    return False


def send_cmd(ser, cmd):
    print(f"> {cmd}")
    ser.write((cmd + "\n").encode())
    time.sleep(0.3)


def break_autoboot(ser):
    print("Czekam na 'Hit any key'...")

    if wait_for(ser, "Hit any key", timeout=5):
        print("Przerywam autoboot...")
        ser.write(b"\n")
        time.sleep(0.5)

        if wait_for(ser, "U-Boot", timeout=3):
            print("Jesteśmy w konsoli U-Boot.")
            return True

    print("Nie udało się wejść do U-Boot.")
    return False


# ------------------------------------------------------------
# IMAGE
# ------------------------------------------------------------

def convert_image(input_path, output_path, quality):
    subprocess.run([
        "convert",
        input_path,
        "-resize", f"{TARGET_RES[0]}x{TARGET_RES[1]}",
        "-background", "black",
        "-gravity", "center",
        "-extent", f"{TARGET_RES[0]}x{TARGET_RES[1]}",
        "-strip",
        "-quality", str(quality),
        output_path
    ], check=True)


def validate_jpeg(path):
    with open(path, "rb") as f:
        data = f.read()

    if not data.startswith(b"\xFF\xD8"):
        return False
    if b"\xFF\xD9" not in data:
        return False
    return True


def pad_to_size(path):
    size = os.path.getsize(path)

    if size > PARTITION_SIZE:
        return False

    if size < PARTITION_SIZE:
        with open(path, "ab") as f:
            f.write(b"\xFF" * (PARTITION_SIZE - size))

    return True


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Użycie: python3 flash_logo_stable.py obraz.jpg")
        sys.exit(1)

    input_file = Path(sys.argv[1])
    if not input_file.is_file():
        print("Brak pliku.")
        sys.exit(1)

    check_dependencies()
    port = detect_port()

    output_file = Path("logo_204800.jpg")

    # --- KONWERSJA ---
    quality = START_QUALITY
    while quality >= MIN_QUALITY:
        print(f"Konwersja (q={quality})")
        convert_image(str(input_file), str(output_file), quality)

        if os.path.getsize(output_file) <= PARTITION_SIZE:
            break

        quality -= QUALITY_STEP

    if quality < MIN_QUALITY:
        print("Nie można zmieścić w 200 KiB.")
        sys.exit(1)

    if not validate_jpeg(output_file):
        print("JPEG uszkodzony.")
        sys.exit(1)

    if not pad_to_size(output_file):
        print("Błąd dopasowania rozmiaru.")
        sys.exit(1)

    print("Plik gotowy.")

    # --- OTWIERAMY PORT ---
    ser = serial.Serial(port, BAUDRATE, timeout=1)

    if not break_autoboot(ser):
        print("Zresetuj urządzenie i spróbuj ponownie.")
        sys.exit(1)

    send_cmd(ser, f"loady {LOAD_ADDR}")

    print("Zamykam port do transferu YMODEM...")
    ser.close()
    time.sleep(0.5)

    # --- YMODEM ---
    print("Start YMODEM (sb)...")
    subprocess.run(
        f"sb {output_file} < {port} > {port}",
        shell=True,
        check=True
    )

    # --- OTWIERAMY PONOWNIE ---
    time.sleep(1)
    ser = serial.Serial(port, BAUDRATE, timeout=1)

    print("Czekam na zakończenie transferu...")
    wait_for(ser, "## Total Size", timeout=20)

    send_cmd(ser, "sf probe")
    send_cmd(ser, f"sf erase {FLASH_ADDR} +{FLASH_SIZE}")
    send_cmd(ser, f"sf write {LOAD_ADDR} {FLASH_ADDR} $filesize")
    send_cmd(ser, "reset")

    ser.close()

    print("\nFLASH ZAKOŃCZONY SUKCESEM ✅")


if __name__ == "__main__":
    main()