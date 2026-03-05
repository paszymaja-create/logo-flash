# logo-flash

Skrypty Python do flashowania niestandardowego logo bootowego na urządzeniu ORNO MD-1080 przez konsolę szeregową U-Boot.

Skrypt konwertuje obraz wejściowy do JPEG o wymiarach 1024x600, dopełnia go do dokładnie 200 KiB (204800 bajtów), przesyła przez YMODEM i zapisuje do pamięci SPI flash.

## Wymagania

- **Python 3.13+**
- **lrzsz** (`sb`) — transfer YMODEM (tylko w trybie flash)
- **uv** — zarządzanie zależnościami

## Instalacja

```bash
uv sync
```

## Użycie

```bash
# Pełny flash (wymaga urządzenia podłączonego przez USB serial)
uv run python3 logo.py obraz.jpg

# Tryb testowy — walidacja konwersji obrazu bez flashowania
uv run python3 logo.py obraz.jpg --test
```

## Pliki

- **`logo.py`** — Główny skrypt z obsługą trybu testowego (`--test`)
- **`flash_logo_stable.py`** — Wcześniejsza wersja bez trybu testowego
