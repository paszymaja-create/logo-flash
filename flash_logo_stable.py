#!/usr/bin/env python3
"""
STABLE AUTO FLASH – ORNO MD-1080
Wersja stabilna bez trybu testowego.
"""

import argparse
from pathlib import Path

from logo_core import check_dependencies, prepare_image, flash_image, _cleanup


def main():
    parser = argparse.ArgumentParser(
        description="Flashowanie logo na ORNO MD-1080 przez U-Boot serial."
    )
    parser.add_argument("image", type=Path, help="Sciezka do obrazu wejsciowego")
    parser.add_argument("--port", type=str, default=None, help="Port szeregowy (np. /dev/ttyUSB0)")
    args = parser.parse_args()

    check_dependencies(need_sb=True)

    output_file = prepare_image(args.image)

    try:
        flash_image(output_file, port=args.port)
    finally:
        _cleanup(output_file)


if __name__ == "__main__":
    main()
