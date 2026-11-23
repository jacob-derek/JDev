#!/usr/bin/env python3
"""Gera os PNGs usados pelo tema Plymouth JDev; requer Pillow."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "assets"
VOID_LOGO = Path("/tmp/void-sim/root/usr/share/void-artwork/void-logo.png")
W, H = 1280, 720
BG = (13, 17, 21)
MUTED = (111, 128, 137)
ACCENT = (137, 164, 171)
DIM = (66, 81, 89)


def font(size: int, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    choices = (["/usr/share/fonts/TTF/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"] if mono else [])
    choices += ["/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    for path in choices:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def text_png(name: str, text: str, size: int, color: tuple[int, int, int], mono: bool = False) -> None:
    f = font(size, mono)
    box = f.getbbox(text)
    image = Image.new("RGBA", (box[2] - box[0] + 8, box[3] - box[1] + 8), (0, 0, 0, 0))
    ImageDraw.Draw(image).text((4 - box[0], 4 - box[1]), text, font=f, fill=(*color, 255))
    image.save(OUT / name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    text_png("titulo.png", "J D E V  /  STANDBY", 27, ACCENT, True)
    text_png("sistema.png", "S I S T E M A", 15, ACCENT, True)
    rows = [
        ("DISTRIBUIÇÃO", "Void Linux"),
        ("INIT", "runit"),
        ("INITRAMFS", "dracut"),
        ("ESTADO", "inicializando"),
    ]
    for idx, (label, value) in enumerate(rows):
        text_png(f"dado-{idx}-label.png", label, 13, DIM, True)
        text_png(f"dado-{idx}-valor.png", value, 17, MUTED, True)

    # Mantém a marca oficial do pacote Void e limita seu tamanho no splash.
    logo = Image.open(VOID_LOGO).convert("RGBA")
    logo.thumbnail((84, 84), Image.Resampling.LANCZOS)
    # Logo monocromática e discreta, como o esquema escuro do JStandby.
    gray = logo.convert("L")
    alpha = gray.point(lambda value: max(0, 255 - value))
    flat = Image.new("RGBA", logo.size, (*ACCENT, 0))
    flat.putalpha(alpha.point(lambda a: a * 210 // 255))
    flat.save(OUT / "void-logo.png")

    divider = Image.new("RGBA", (500, 2), (0, 0, 0, 0))
    ImageDraw.Draw(divider).line((0, 1, 499, 1), fill=(*DIM, 190), width=1)
    divider.save(OUT / "divisoria.png")

    track = Image.new("RGBA", (440, 5), (0, 0, 0, 0))
    ImageDraw.Draw(track).rounded_rectangle((0, 0, 439, 4), radius=2, fill=(*DIM, 100))
    track.save(OUT / "progresso-trilho.png")
    for pct in range(101):
        fill = Image.new("RGBA", (440, 5), (0, 0, 0, 0))
        width = round(439 * pct / 100)
        if width:
            ImageDraw.Draw(fill).rounded_rectangle((0, 0, width, 4), radius=2, fill=(*ACCENT, 225))
        fill.save(OUT / f"progresso-{pct}.png")

    # Cada quadro já vem rasterizado: o script Plymouth não desenha glifos.
    for frame in range(20):
        sprite = Image.new("RGBA", (440, 22), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sprite)
        for dot in range(20):
            x = 8 + dot * 22
            draw.ellipse((x - 2, 9, x + 2, 13), fill=(*DIM, 145))
        x = 8 + frame * 22
        draw.polygon([(x, 5), (x + 5, 11), (x, 17), (x - 5, 11)], fill=(*ACCENT, 245))
        sprite.save(OUT / f"indicador-{frame}.png")

    for frame, alpha in enumerate((110, 175, 225, 175)):
        footer = Image.new("RGBA", (180, 28), (0, 0, 0, 0))
        ImageDraw.Draw(footer).ellipse((3, 12, 9, 18), fill=(*MUTED, alpha))
        ImageDraw.Draw(footer).text((17, 3), "repouso", font=font(18, True), fill=(*MUTED, alpha))
        footer.save(OUT / f"rodape-{frame}.png")

    # Preview de referência do desenho, para conferência sem Plymouth.
    preview = Image.new("RGB", (W, H), BG)
    p = ImageDraw.Draw(preview)
    p.text((W // 2, 110), "J D E V  /  STANDBY", font=font(27, True), fill=ACCENT, anchor="mm")
    p.line((W // 2 - 250, 140, W // 2 + 250, 140), fill=DIM)
    preview.alpha_composite(flat, (W // 2 - 250, 208)) if preview.mode == "RGBA" else preview.paste(flat, (W // 2 - 250, 208), flat)
    p = ImageDraw.Draw(preview)
    p.text((W // 2 - 115, 226), "S I S T E M A", font=font(15, True), fill=ACCENT)
    for idx, (label, value) in enumerate(rows):
        y = 266 + idx * 43
        p.text((W // 2 - 115, y), label, font=font(12, True), fill=DIM)
        p.text((W // 2 - 115, y + 17), value, font=font(16, True), fill=MUTED)
    p.line((W // 2 - 220, 535, W // 2 + 220, 535), fill=(66, 81, 89))
    p.rounded_rectangle((W // 2 - 220, 568, W // 2 + 220, 573), radius=2, fill=(41, 52, 59))
    p.rounded_rectangle((W // 2 - 220, 568, W // 2 + 95, 573), radius=2, fill=ACCENT)
    for dot in range(20):
        x = W // 2 - 220 + 8 + dot * 22
        p.ellipse((x - 2, 614, x + 2, 618), fill=DIM)
    x = W // 2 - 220 + 8 + 9 * 22
    p.polygon([(x, 610), (x + 5, 616), (x, 622), (x - 5, 616)], fill=ACCENT)
    p.ellipse((W // 2 - 51, 667, W // 2 - 43, 675), fill=MUTED)
    p.text((W // 2 - 36, 661), "repouso", font=font(18, True), fill=MUTED)
    preview.save(ROOT / "preview.png")
    print(f"Gerados {len(list(OUT.glob('*.png')))} PNGs em {OUT}")
    print(f"Preview: {ROOT / 'preview.png'}")


if __name__ == "__main__":
    main()
