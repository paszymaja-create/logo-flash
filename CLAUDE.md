# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python scripts for flashing a custom boot logo onto the ORNO MD-1080 device via U-Boot serial console. The scripts convert an input image to a constrained JPEG, pad it to exactly 200 KiB (204800 bytes), transfer it over YMODEM, and write it to SPI flash.

## Key Scripts

- **`logo_core.py`** — Shared functions, constants, and types used by both wrappers.
- **`logo.py`** — Main script. Supports `--test`, `--port`, `--quality` flags.
- **`flash_logo_stable.py`** — Simpler wrapper without test mode. Supports `--port`.

## Running

```bash
# Full flash (requires device connected via USB serial)
uv run python3 logo.py image.jpg

# Test mode — validate image conversion only, no flashing
uv run python3 logo.py image.jpg --test

# Custom port and quality
uv run python3 logo.py image.jpg --port /dev/ttyUSB1 --quality 75
```

## External Dependencies

- **Pillow** — image resizing/conversion (Python package, installed via `uv sync`)
- **lrzsz** (`sb`) — YMODEM file transfer
- **pyserial** — serial port communication (Python package, installed via `uv sync`)

## Hardware Constants

Target device: ORNO MD-1080. Key flash parameters in `logo_core.py`:
- Partition size: 204800 bytes (200 KiB)
- Target resolution: 1024x600
- Flash address: `0x23b000`, size: `0x32000`
- Load address: `0x82000000`
- Baud rate: 115200

## Language

Code comments and UI messages are in Polish.
