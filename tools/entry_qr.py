"""Generate the QR code for Orviqo's public entry point (the /start link).

The QR encodes the app's /start URL, not a raw wa.me link, so a printed or posted
code keeps working if the business number ever changes. Writes an SVG (for the
web and print) and a PNG (for socials).

    uv run --with segno python tools/entry_qr.py
    uv run --with segno python tools/entry_qr.py --url https://orviqo.fly.dev/start --out .
"""

from __future__ import annotations

import argparse
from pathlib import Path

import segno


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the /start QR code.")
    parser.add_argument("--url", default="https://orviqo.fly.dev/start", help="URL to encode.")
    parser.add_argument(
        "--out", default="content/audience/assets", help="Directory to write the images into."
    )
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    qr = segno.make(args.url, error="m")
    for name, scale in (("orviqo-start-qr.svg", 10), ("orviqo-start-qr.png", 16)):
        path = out / name
        qr.save(path, scale=scale, border=4)
        print("wrote", path)


if __name__ == "__main__":
    main()
