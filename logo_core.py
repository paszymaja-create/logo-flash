"""
Wspoldzielone funkcje i stale dla skryptow logo-flash (ORNO MD-1080).
"""

import io
import os
import sys
import time
import glob
import shlex
import shutil
import tempfile
import subprocess
from pathlib import Path
from typing import Optional

import serial
from PIL import Image

# --- KONFIG ---
PARTITION_SIZE: int = 204800
TARGET_RES: tuple[int, int] = (1024, 600)
BAUDRATE: int = 115200
LOAD_ADDR: str = "0x82000000"
FLASH_ADDR: str = "0x23b000"
FLASH_SIZE: str = "0x32000"

START_QUALITY: int = 85
MIN_QUALITY: int = 60
QUALITY_STEP: int = 5

MAX_INPUT_SIZE: int = 50 * 1024 * 1024  # 50 MB
MAX_BUFFER_SIZE: int = 64 * 1024  # 64 KiB


# ------------------------------------------------------------
# DEPENDENCIES
# ------------------------------------------------------------

def check_dependencies(need_sb: bool = True) -> None:
    if need_sb and not shutil.which("sb"):
        print("Brak narzedzia: sb")
        sys.exit(1)


# ------------------------------------------------------------
# INPUT VALIDATION
# ------------------------------------------------------------

def validate_input_image(path: Path) -> None:
    if not path.is_file():
        print(f"Blad: Plik '{path}' nie istnieje.")
        sys.exit(1)

    size = path.stat().st_size
    if size > MAX_INPUT_SIZE:
        print(f"Blad: Plik wejsciowy za duzy ({size} bajtow, maks. {MAX_INPUT_SIZE}).")
        sys.exit(1)

    try:
        with Image.open(path) as img:
            img.verify()
    except Exception as e:
        print(f"Blad: Plik nie jest prawidlowym obrazem: {e}")
        sys.exit(1)


# ------------------------------------------------------------
# SERIAL
# ------------------------------------------------------------

def detect_port() -> str:
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    if not ports:
        print("Nie znaleziono portu USB.")
        sys.exit(1)
    print(f"Uzywam portu: {ports[0]}")
    return ports[0]


def wait_for(ser: serial.Serial, text: str, timeout: float = 5) -> bool:
    end = time.time() + timeout
    buffer = b""

    while time.time() < end:
        if ser.in_waiting:
            buffer += ser.read(ser.in_waiting)
            if len(buffer) > MAX_BUFFER_SIZE:
                buffer = buffer[-MAX_BUFFER_SIZE:]
            if text.encode() in buffer:
                return True
        time.sleep(0.05)
    return False


def send_cmd(ser: serial.Serial, cmd: str) -> None:
    print(f"> {cmd}")
    ser.write((cmd + "\n").encode())
    time.sleep(0.3)


def break_autoboot(ser: serial.Serial) -> bool:
    print("Czekam na 'Hit any key'...")

    if wait_for(ser, "Hit any key", timeout=5):
        print("Przerywam autoboot...")
        ser.write(b"\n")
        time.sleep(0.5)

        if wait_for(ser, "U-Boot", timeout=3):
            print("Jestesmy w konsoli U-Boot.")
            return True

    print("Nie udalo sie wejsc do U-Boot.")
    return False


def open_serial(port: str) -> serial.Serial:
    try:
        return serial.Serial(port, BAUDRATE, timeout=1)
    except serial.SerialException as e:
        print(f"Blad otwarcia portu {port}: {e}")
        sys.exit(1)


# ------------------------------------------------------------
# IMAGE
# ------------------------------------------------------------

def convert_image(input_path: str, output_path: str, quality: int) -> None:
    try:
        with Image.open(input_path) as img:
            img = img.convert("RGB")
            img.thumbnail(TARGET_RES, Image.LANCZOS)

            canvas = Image.new("RGB", TARGET_RES, (0, 0, 0))
            offset = ((TARGET_RES[0] - img.width) // 2, (TARGET_RES[1] - img.height) // 2)
            canvas.paste(img, offset)

            canvas.save(output_path, "JPEG", quality=quality, optimize=True)
    except Exception as e:
        print(f"Blad konwersji obrazu: {e}")
        sys.exit(1)


def validate_jpeg(path: Path) -> bool:
    with open(path, "rb") as f:
        data = f.read()

    if not data.startswith(b"\xFF\xD8"):
        return False
    if b"\xFF\xD9" not in data:
        return False
    return True


def pad_to_size(path: Path) -> bool:
    size = os.path.getsize(path)

    if size > PARTITION_SIZE:
        return False

    if size < PARTITION_SIZE:
        with open(path, "ab") as f:
            f.write(b"\xFF" * (PARTITION_SIZE - size))

    return True


def create_temp_output() -> Path:
    fd, path = tempfile.mkstemp(suffix=".jpg", prefix="logo_")
    os.close(fd)
    return Path(path)


# ------------------------------------------------------------
# KONWERSJA (wspolny flow)
# ------------------------------------------------------------

def prepare_image(input_file: Path, quality: Optional[int] = None) -> Path:
    validate_input_image(input_file)

    output_file = create_temp_output()

    start_q = quality if quality is not None else START_QUALITY
    q = start_q
    success = False

    try:
        while q >= MIN_QUALITY:
            print(f"Konwersja (jakosc={q})...")
            convert_image(str(input_file), str(output_file), q)

            if os.path.getsize(output_file) <= PARTITION_SIZE:
                success = True
                break
            q -= QUALITY_STEP

        if not success:
            print(f"Blad: Nie mozna zmiescic obrazu w limicie {PARTITION_SIZE} bajtow.")
            _cleanup(output_file)
            sys.exit(1)

        if not validate_jpeg(output_file):
            print("Blad: Wygenerowany plik JPEG jest uszkodzony.")
            _cleanup(output_file)
            sys.exit(1)

        if not pad_to_size(output_file):
            print("Blad: Plik wynikowy przekroczyl rozmiar partycji po paddingu.")
            _cleanup(output_file)
            sys.exit(1)

        print(f"Sukces! Plik przygotowany: {output_file} ({os.path.getsize(output_file)} bajtow)")
        return output_file

    except BaseException:
        _cleanup(output_file)
        raise


def _cleanup(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


# ------------------------------------------------------------
# FLASH
# ------------------------------------------------------------

def flash_image(output_file: Path, port: Optional[str] = None) -> None:
    if port is None:
        port = detect_port()

    ser = open_serial(port)

    try:
        if not break_autoboot(ser):
            print("Blad: Nie udalo sie przerwac bootowania. Zresetuj urzadzenie i sprobuj ponownie.")
            sys.exit(1)

        send_cmd(ser, f"loady {LOAD_ADDR}")

        print("Zamykam port do transferu YMODEM...")
        ser.close()
        time.sleep(0.5)

        # --- YMODEM ---
        print("Start transferu YMODEM (sb)...")
        try:
            subprocess.run(
                f"sb {shlex.quote(str(output_file))} < {shlex.quote(port)} > {shlex.quote(port)}",
                shell=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"Blad transferu YMODEM (sb): kod {e.returncode}")
            sys.exit(1)

        # --- OTWIERAMY PONOWNIE ---
        time.sleep(1)
        ser = open_serial(port)

        print("Czekam na potwierdzenie rozmiaru transferu...")
        if not wait_for(ser, "## Total Size", timeout=20):
            print("Blad: Nie otrzymano potwierdzenia transferu.")
            sys.exit(1)

        send_cmd(ser, "sf probe")
        time.sleep(0.5)

        send_cmd(ser, f"sf erase {FLASH_ADDR} +{FLASH_SIZE}")
        if not wait_for(ser, "OK", timeout=10):
            print("Blad: sf erase nie powiodlo sie.")
            sys.exit(1)

        send_cmd(ser, f"sf write {LOAD_ADDR} {FLASH_ADDR} $filesize")
        if not wait_for(ser, "OK", timeout=10):
            print("Blad: sf write nie powiodlo sie.")
            sys.exit(1)

        send_cmd(ser, "reset")
    finally:
        if ser.is_open:
            ser.close()

    print("\nFLASH ZAKONCZONY SUKCESEM")
