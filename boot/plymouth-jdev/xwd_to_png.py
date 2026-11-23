#!/usr/bin/env python3
"""Converte uma captura XWD do Xvfb para PNG usando Pillow."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PIL import Image


def component(pixel: int, mask: int) -> int:
    if not mask:
        return 0
    shift = (mask & -mask).bit_length() - 1
    value = (pixel & mask) >> shift
    return value * 255 // (mask >> shift)


def main() -> int:
    if len(sys.argv) != 3:
        print("uso: xwd_to_png.py ENTRADA.xwd SAIDA.png", file=sys.stderr)
        return 2
    data = Path(sys.argv[1]).read_bytes()
    fields = struct.unpack(">25I", data[:100])
    header_size, version, pixmap_format, depth, width, height = fields[:6]
    byte_order, bits_per_pixel, bytes_per_line = fields[7], fields[11], fields[12]
    red_mask, green_mask, blue_mask = fields[14:17]
    ncolors = fields[19]
    if version != 7 or pixmap_format != 2 or bits_per_pixel not in (24, 32):
        raise SystemExit(f"XWD nao suportado: versao={version}, formato={pixmap_format}, bpp={bits_per_pixel}")
    offset = header_size + ncolors * 12
    raw = data[offset:]
    if len(raw) < bytes_per_line * height:
        raise SystemExit("arquivo XWD truncado")
    output = bytearray(width * height * 3)
    bpp = bits_per_pixel // 8
    for y in range(height):
        row = raw[y * bytes_per_line:(y + 1) * bytes_per_line]
        for x in range(width):
            pixel = int.from_bytes(row[x * bpp:(x + 1) * bpp], "little" if byte_order == 0 else "big")
            pos = (y * width + x) * 3
            output[pos] = component(pixel, red_mask)
            output[pos + 1] = component(pixel, green_mask)
            output[pos + 2] = component(pixel, blue_mask)
    Image.frombytes("RGB", (width, height), bytes(output)).save(sys.argv[2])
    print(f"PNG: {sys.argv[2]} ({width}x{height}, depth {depth})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
