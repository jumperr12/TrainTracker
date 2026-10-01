"""Write fully transparent placeholder PNGs for every icon the frontend expects.

    python -m scripts.make_placeholder_icons           # only creates missing files
    python -m scripts.make_placeholder_icons --force   # overwrite (e.g. to reset real icons)

Drop real artwork into frontend/public/icons/ under the same names and sizes; no code change needed.
Keep this list in sync with frontend/src/lib/icons.ts.
"""

import argparse
import struct
import zlib
from pathlib import Path

ICONS_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public" / "icons"

ICONS = {
    "train-eip.png": 48,
    "train-eic.png": 48,
    "train-ic.png": 48,
    "train-tlk.png": 48,
    "train-ec.png": 48,
    "train-en.png": 48,
    "train-default.png": 48,
    "station.png": 16,
}


def transparent_png(size: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    raw = b"".join(b"\x00" + b"\x00\x00\x00\x00" * size for _ in range(size))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in ICONS.items():
        path = ICONS_DIR / name
        if path.exists() and not args.force:
            print(f"keep    {path.name}")
            continue
        path.write_bytes(transparent_png(size))
        print(f"created {path.name} ({size}x{size}, transparent)")


if __name__ == "__main__":
    main()
