"""jwall - tema que nasce do wallpaper: acha a cor de destaque da imagem e deriva fundos, foco e bordas dela.

Uso:   JTHEME=wallpaper   (ou `echo wallpaper > ~/.config/jdev/theme`)   - o jtheme chama gerar() sozinho.
Teste: python3 jwall.py [imagem]   mostra a cor achada e a paleta gerada.

Só as cores de "chrome" (fundos, foco, bordas, flutuante) vêm do wallpaper; as cores de sintaxe/ANSI
(verde, azul, amarelo...) ficam as do tema base, para o código continuar legível. Sem Pillow ou sem
imagem, gerar() devolve None e o jtheme usa o tema padrão. O resultado fica em cache
(~/.cache/jdev/wallpaper-theme.json), então a imagem só é lida de novo quando muda.
"""
from __future__ import annotations

import colorsys
import json
import math
import os
import sys
from pathlib import Path

EXT = ("png", "jpg", "jpeg", "webp", "PNG", "JPG", "JPEG", "WEBP")
CHAVES_CHROME = ("bg_deep", "bg", "bg_alt", "bg_hover", "line", "line2", "select", "focus", "border",
                 "border_idle", "header_idle", "header_focus", "on_accent", "float", "secondary")


def _hex(r: float, g: float, b: float) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in (r, g, b))


def hls_hex(h: float, l: float, s: float) -> str:
    return _hex(*colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s))))


def achar_wallpaper() -> Path | None:
    """Mesma regra do jwm-wallpaper: JWM_WALLPAPER, horizontal.*, wallpaper.*, ou qualquer imagem da pasta."""
    pedido = os.environ.get("JWM_WALLPAPER", "").strip()
    if pedido:
        p = Path(os.path.expanduser(pedido))
        if p.is_file():
            return p
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "jdev"
    for nome in ("horizontal", "wallpaper", "vertical"):
        for e in EXT:
            if (base / f"{nome}.{e}").is_file():
                return base / f"{nome}.{e}"
    try:
        for p in sorted(base.iterdir()):
            if p.suffix.lstrip(".") in EXT and p.is_file():
                return p
    except OSError:
        pass
    return None


def cor_de_destaque(pixels) -> tuple[float, float] | None:
    """(matiz 0-1, saturação 0-1) da cor que "grita" na imagem, ou None se for (quase) cinza.
    `pixels`: sequência de (r,g,b) 0-255. Histograma de matiz ponderado por saturação e por quão
    longe do preto/branco o pixel está. Wallpaper escuro? Tenta de novo com limites mais tolerantes."""
    pixels = list(pixels)
    for s_min, l_min in ((0.25, 0.10), (0.15, 0.04)):
        r = _destaque(pixels, s_min, l_min)
        if r is not None:
            return r
    return None


def _destaque(pixels, s_min: float, l_min: float):
    bins = [0.0] * 36
    soma_s = [0.0] * 36
    peso_s = [0.0] * 36
    total = 0
    for r, g, b in pixels:
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        total += 1
        if s < s_min or l < l_min or l > 0.92:
            continue
        w = s * (1 - abs(l - 0.5) * 1.6)
        if w <= 0:
            continue
        i = int(h * 36) % 36
        bins[i] += w
        soma_s[i] += s * w
        peso_s[i] += w
    if total == 0 or max(bins) < total * 0.004:      # menos de ~0,4% de pixels coloridos: é cinza
        return None
    vizinhos = lambda i: (i - 1, i, (i + 1) % 36)  # noqa: E731
    melhor = max(range(36), key=lambda i: sum(bins[j] for j in vizinhos(i)))
    x = y = 0.0
    for j in vizinhos(melhor):    # matiz médio circular dos 3 bins (evita eleger um bin isolado)
        ang = (j + 0.5) / 36 * 2 * math.pi
        x += bins[j] * math.cos(ang)
        y += bins[j] * math.sin(ang)
    h = (math.atan2(y, x) / (2 * math.pi)) % 1.0
    ps = sum(peso_s[j] for j in vizinhos(melhor))
    s = sum(soma_s[j] for j in vizinhos(melhor)) / ps if ps else 0.6
    return h, s


def derivar(base: dict, acento) -> dict:
    """Tema = base escura + chrome (fundos/foco/bordas) tingido pelo acento. `acento` = (matiz, sat) ou None."""
    t = dict(base)
    if acento is None:                      # imagem cinza: só aproveita os tons neutros do tema base
        return t
    h, s = acento
    s = max(0.55, min(0.88, s))
    tint = min(0.34, 0.12 + s * 0.2)        # quanto de cor vai nos fundos (pouco: o texto precisa respirar)
    t.update(
        bg_deep=hls_hex(h, 0.035, tint), bg=hls_hex(h, 0.06, tint), bg_alt=hls_hex(h, 0.095, tint),
        bg_hover=hls_hex(h, 0.15, tint), line=hls_hex(h, 0.13, tint * 0.9), line2=hls_hex(h, 0.23, tint * 0.8),
        select=hls_hex(h, 0.27, min(0.5, s * 0.6)),
        focus=hls_hex(h, 0.58, s), border=hls_hex(h, 0.30, 0.16), border_idle=hls_hex(h, 0.13, tint * 0.9),
        header_idle=hls_hex(h, 0.62, 0.14), header_focus=hls_hex(h, 0.06, tint),
        on_accent=hls_hex(h, 0.07, 0.4),
        float=hls_hex(h + 0.075, 0.66, max(0.4, s * 0.62)),    # vizinho no círculo de cores, mais calmo
        secondary=hls_hex(h, 0.62, 0.12),
    )
    return t


def _assinatura(p: Path) -> str:
    st = p.stat()
    return f"{p}|{st.st_mtime_ns}|{st.st_size}"


def _cache_path() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "jdev" / "wallpaper-theme.json"


def gerar(base: dict) -> dict | None:
    """Tema derivado do wallpaper atual (com cache), ou None se não der (sem imagem/Pillow/erro)."""
    img = achar_wallpaper()
    if img is None:
        return None
    try:
        sig = _assinatura(img)
        cache = _cache_path()
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            if c.get("sig") == sig and c.get("base") == base.get("label") and isinstance(c.get("chrome"), dict):
                return {**base, **{k: v for k, v in c["chrome"].items() if k in CHAVES_CHROME}}
        except (OSError, ValueError):
            pass
        from PIL import Image
        with Image.open(img) as im:
            im = im.convert("RGB")
            im.thumbnail((96, 96))
            dados = getattr(im, "get_flattened_data", im.getdata)()
            acento = cor_de_destaque(list(dados))
        tema = derivar(base, acento)
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"sig": sig, "base": base.get("label"),
                                         "chrome": {k: tema[k] for k in CHAVES_CHROME if k in tema}}),
                             encoding="utf-8")
        except OSError:
            pass
        return tema
    except Exception:                       # decorativo: nunca derruba quem importa o jtheme
        return None


if __name__ == "__main__":
    import jtheme
    if len(sys.argv) > 1:
        os.environ["JWM_WALLPAPER"] = sys.argv[1]
    base = jtheme.THEMES["void"]
    img = achar_wallpaper()
    print("imagem:", img)
    t = gerar(base)
    if t is None:
        print("não deu (sem imagem ou sem Pillow)")
    else:
        for k in CHAVES_CHROME:
            print(f"  {k:<13}{t[k]}")
