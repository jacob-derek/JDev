#!/usr/bin/env python3
"""JGrab - baixa albuns com yt-dlp e CONFERE a ordem das faixas pelo MusicBrainz.

Uso:
  JGrab.py --doctor                 testa se yt-dlp, ffmpeg e o JS do YouTube estao ok
  JGrab.py --scan albums.txt        so confere (acha as faixas e mostra o relatorio), nao baixa
  JGrab.py albums.txt               confere e baixa
  JGrab.py albums.txt --out /mnt/sd --only iowa      (so os albuns que contem "iowa")

albums.txt (uma linha por album):
  Artista | Album
  Artista | Album | https://www.youtube.com/playlist?list=...   (link opcional)

Saida: <out>/<Artista>/<Album (ano)>/NN - Titulo.mp3 + cover.jpg, com tags e capa embutida.
Dependencias (Void): sudo xbps-install -S yt-dlp ffmpeg nodejs
"""
import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

MB = "https://musicbrainz.org/ws/2"
CAA = "https://coverartarchive.org"
UA = "JGrab/1.0 (script pessoal de organizacao de musicas)"
BAD_WORDS = ("live", "cover", "remix", "reaction", "karaoke", "instrumental", "slowed",
             "reverb", "sped up", "nightcore", "8d", "tribute", "tutorial", "lesson",
             "full album", "bass boosted", "acoustic", "mashup", "demo")
OK_SCORE, DOUBT_SCORE = 55, 35
PLAYLIST_FILTER = "&sp=EgIQAw%253D%253D"  # filtro "Playlists" da busca do YouTube

_last_mb = [0.0]
_flags_cache = {}


# ------------------------------------------------------------ texto / fuzzy
def norm(s, drop_brackets=True):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    if drop_brackets:
        t = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", s)
        if re.search(r"\w", t):       # "(sic)" nao pode virar vazio
            s = t
    s = re.sub(r"\b(feat|ft)\b\.?.*", " ", s)
    return re.sub(r"[\W_]+", " ", s).strip()


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    r = difflib.SequenceMatcher(None, a, b).ratio()
    if (a in b or b in a) and min(len(a), len(b)) >= 4:
        r = max(r, 0.9)
    return r


NOISE = r"(official|audio|video|lyrics?|visualizer|remaster(ed)?|hd|hq)"


def clean_yt_title(title, artist):
    title = re.sub(r"^\s*" + re.escape(artist) + r"\s*[-–—:|]\s*", "", title, flags=re.I)
    title = re.sub(r"[\(\[][^\)\]]*\b" + NOISE + r"\b[^\)\]]*[\)\]]", " ", title, flags=re.I)
    title = re.sub(r"\b" + NOISE + r"\b", " ", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" -–—|")


def safe(name, limit=110):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return (name or "_")[:limit].rstrip(" .")


def last_line(text):
    lines = [l for l in (text or "").strip().splitlines() if l.strip()]
    return lines[-1][:300] if lines else "erro desconhecido"


def say(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------- rede (MB)
def http_bytes(url, mb=False):
    if mb:
        wait = 1.1 - (time.time() - _last_mb[0])
        if wait > 0:
            time.sleep(wait)
        _last_mb[0] = time.time()
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json, image/*"})
    with urlopen(req, timeout=40) as r:
        return r.read()


def http_json(url):
    return json.loads(http_bytes(url, mb=True).decode("utf-8"))


def artist_credit(group):
    return " ".join(c.get("name", "") for c in group.get("artist-credit", []) if isinstance(c, dict))


def mb_tracklist(artist, album):
    """Acha o album no MusicBrainz e devolve a lista OFICIAL de faixas (na ordem do disco)."""
    queries = [(f'releasegroup:"{album}" AND artist:"{artist}"', False),
               (f"{album} {artist}", True)]
    group = None
    for q, loose in queries:
        data = http_json(f"{MB}/release-group/?query={quote(q)}&limit=8&fmt=json")
        for g in sorted(data.get("release-groups") or [],
                        key=lambda g: (sim(g.get("title", ""), album), g.get("score", 0)),
                        reverse=True):
            if sim(g.get("title", ""), album) < 0.6:
                continue
            if loose and sim(artist_credit(g), artist) < 0.5:
                continue
            group = g
            break
        if group:
            break
    if not group:
        return None
    url = f"{MB}/release?release-group={group['id']}&inc=media&limit=50&fmt=json"
    releases = http_json(url + "&status=official").get("releases") or http_json(url).get("releases") or []
    releases = [r for r in releases if sum(m.get("track-count", 0) for m in r.get("media", [])) > 0]
    if not releases:
        return None

    def key(r):
        date = (r.get("date") or "9999")
        date = date + "-99-99"[len(date) - 4:] if len(date) < 10 else date
        return date, sum(m.get("track-count", 0) for m in r.get("media", []))

    chosen = sorted(releases, key=key)[0]
    rel = http_json(f"{MB}/release/{chosen['id']}?inc=recordings&fmt=json")
    tracks = []
    for medium in rel.get("media", []):
        for t in medium.get("tracks", []):
            ms = t.get("length") or (t.get("recording") or {}).get("length")
            tracks.append({"title": t.get("title", ""), "ms": ms})
    if not tracks:
        return None
    year = (rel.get("date") or group.get("first-release-date") or "")[:4]
    return {"title": rel.get("title") or group.get("title") or album, "year": year,
            "mbid": chosen["id"], "rgid": group["id"], "tracks": tracks}


def fetch_cover(info, dest_dir):
    for url in (f"{CAA}/release/{info['mbid']}/front-500",
                f"{CAA}/release-group/{info['rgid']}/front-500"):
        try:
            data = http_bytes(url)
        except (URLError, HTTPError, OSError):
            continue
        if data[:2] == b"\xff\xd8":
            ext = ".jpg"
        elif data[:4] == b"\x89PNG":
            ext = ".png"
        else:
            continue
        path = Path(dest_dir) / ("cover" + ext)
        path.write_bytes(data)
        return path
    return None


# ----------------------------------------------------------------- yt-dlp
def have_flag(flag):
    if "help" not in _flags_cache:
        try:
            _flags_cache["help"] = subprocess.run(["yt-dlp", "--help"], capture_output=True,
                                                  text=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            _flags_cache["help"] = ""
    return flag in _flags_cache["help"]


def base_flags(remote_ejs=True):
    flags = ["--no-warnings", "--no-color"]
    if have_flag("--js-runtimes"):
        for exe, name in (("deno", "deno"), ("node", "node"), ("bun", "bun"), ("qjs", "quickjs")):
            if shutil.which(exe):
                flags += ["--js-runtimes", name]
                break
        if remote_ejs and have_flag("--remote-components"):
            flags += ["--remote-components", "ejs:github"]
    return flags


class YT:
    def __init__(self, remote_ejs=True):
        self.flags = base_flags(remote_ejs)

    def run(self, *args, timeout=240):
        return subprocess.run(["yt-dlp", *self.flags, *args], capture_output=True,
                              text=True, timeout=timeout)

    def entries(self, target, timeout=240):
        r = self.run("-J", "--flat-playlist", target, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(last_line(r.stderr))
        data = json.loads(r.stdout)
        out = []
        for e in data.get("entries") or []:
            if not e:
                continue
            vid = e.get("id", "")
            out.append({"id": vid, "title": e.get("title") or "",
                        "url": e.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else ""),
                        "duration": e.get("duration"),
                        "channel": e.get("channel") or e.get("uploader") or ""})
        return out

    def search(self, query, n=8):
        return self.entries(f"ytsearch{n}:{query}")

    def fetch_thumb(self, url, folder):
        out = str(Path(folder) / "cover.%(ext)s")
        r = self.run("--skip-download", "--write-thumbnail", "--convert-thumbnails", "jpg",
                     "--no-playlist", "-o", out, url, timeout=120)
        path = Path(folder) / "cover.jpg"
        return path if r.returncode == 0 and path.exists() else None

    def download(self, url, workdir, fmt):
        out = str(Path(workdir) / "dl.%(ext)s")
        r = self.run("-x", "--audio-format", fmt, "--audio-quality", "0", "--no-playlist",
                     "-o", out, url, timeout=1200)
        if r.returncode != 0:
            raise RuntimeError(last_line(r.stderr))
        files = sorted(Path(workdir).glob(f"dl.{fmt}")) or sorted(Path(workdir).glob("dl.*"))
        if not files:
            raise RuntimeError("o yt-dlp terminou mas nao gerou arquivo")
        return files[0]


def score_candidate(c, track, artist):
    s = 40 * sim(track["title"], clean_yt_title(c["title"], artist))
    ms, dur = track.get("ms"), c.get("duration")
    if ms and dur:
        d = abs(dur - ms / 1000)
        s += 40 if d <= 2 else 30 if d <= 5 else 15 if d <= 10 else 0 if d <= 20 else -30 if d <= 60 else -60
    chan, art = norm(c.get("channel", ""), False), norm(artist, False)
    if chan.endswith("topic"):
        s += 25
    elif art and art in chan:
        s += 15
    if "vevo" in chan:
        s += 8
    low, want = c["title"].lower(), track["title"].lower()
    for w in BAD_WORDS:
        pat = rf"\b{re.escape(w)}\b"
        if re.search(pat, low) and not re.search(pat, want):
            s -= 60
            break
    return s


def verdict(score):
    return "ok" if score >= OK_SCORE else "duvida" if score >= DOUBT_SCORE else "fraca"


def pick_for_track(yt, artist, track):
    cands = yt.search(f"{artist} {track['title']}")
    cands = [c for c in cands if c.get("url")]
    if not cands:
        return None, -999
    ranked = sorted(((score_candidate(c, track, artist), c) for c in cands),
                    key=lambda x: x[0], reverse=True)
    return ranked[0][1], ranked[0][0]


def match_playlist(tracks, entries, artist):
    """Casa cada faixa oficial com uma entrada da playlist. Devolve (matches, extras)."""
    used, matches = set(), []
    for t in tracks:
        best, best_score = None, 0.0
        for i, e in enumerate(entries):
            if i in used:
                continue
            s = sim(t["title"], clean_yt_title(e["title"], artist))
            ms, dur = t.get("ms"), e.get("duration")
            close = bool(ms and dur and abs(dur - ms / 1000) <= 3)
            if s >= 0.55 or (close and s >= 0.35):
                s += 0.2 if close else 0
                if s > best_score:
                    best, best_score = i, s
        if best is not None:
            used.add(best)
        matches.append(best)
    extras = [i for i in range(len(entries)) if i not in used]
    return matches, extras


def order_report(matches):
    seq = [m for m in matches if m is not None]
    return all(a < b for a, b in zip(seq, seq[1:]))


# ------------------------------------------------------------- tags / arquivos
def tag_file(src, dst, meta, cover, fmt):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    if cover:
        cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v"]
    else:
        cmd += ["-map", "0:a"]
    cmd += ["-c", "copy"]
    if fmt == "mp3":
        cmd += ["-id3v2_version", "3"]
    for k, v in meta.items():
        cmd += ["-metadata", f"{k}={v}"]
    if cover:
        cmd += ["-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)",
                "-disposition:v", "attached_pic"]
    cmd.append(str(dst))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(last_line(r.stderr))


# ------------------------------------------------------------------ album
def plan_album(yt, artist, album, url):
    """Monta o plano: lista de faixas {n,title,ms,url,flag,note} + info do MusicBrainz."""
    info, notes = None, []
    try:
        info = mb_tracklist(artist, album)
    except (URLError, HTTPError, OSError, ValueError) as exc:
        notes.append(f"MusicBrainz indisponivel ({exc}); sem como conferir a ordem oficial")
    if info is None and not notes:
        notes.append("album nao encontrado no MusicBrainz; vou usar a ordem da playlist")

    plan = []
    if url or info is None:
        if not url:
            for q in (f"{artist} {album}", f"{artist} {album} full album"):
                try:
                    found = yt.entries("https://www.youtube.com/results?search_query="
                                       + quote(q) + PLAYLIST_FILTER)
                except (RuntimeError, ValueError):
                    continue
                found = [e for e in found if "list=" in e.get("url", "")]
                found.sort(key=lambda e: sim(e["title"], album) + (0.3 if norm(e.get("channel", ""), False).endswith("topic") else 0),
                           reverse=True)
                if found and sim(found[0]["title"], album) >= 0.5:
                    url = found[0]["url"]
                    notes.append(f"playlist encontrada automaticamente: {found[0]['title']}")
                    break
        if not url:
            raise RuntimeError("nao achei a playlist; coloque o link dela na 3a coluna do albums.txt")
        entries = yt.entries(url)
        if not entries:
            raise RuntimeError("a playlist veio vazia")
        if info:
            matches, extras = match_playlist(info["tracks"], entries, artist)
            if not order_report(matches):
                notes.append("a ordem da playlist e DIFERENTE da oficial; vou numerar pela oficial")
            for i, (t, m) in enumerate(zip(info["tracks"], matches), 1):
                if m is None:
                    plan.append({"n": i, "title": t["title"], "ms": t["ms"], "url": None,
                                 "flag": "faltando", "note": "nao esta na playlist"})
                else:
                    e = entries[m]
                    plan.append({"n": i, "title": t["title"], "ms": t["ms"], "url": e["url"],
                                 "flag": "ok", "note": f"playlist: {e['title']}"})
            if extras:
                notes.append("faixas extras na playlist (ignoradas): "
                             + "; ".join(entries[i]["title"] for i in extras))
        else:
            for i, e in enumerate(entries, 1):
                plan.append({"n": i, "title": clean_yt_title(e["title"], artist),
                             "ms": (e["duration"] or 0) * 1000 or None, "url": e["url"],
                             "flag": "semconf", "note": f"playlist: {e['title']}"})
    else:
        for i, t in enumerate(info["tracks"], 1):
            try:
                cand, score = pick_for_track(yt, artist, t)
            except RuntimeError as exc:
                plan.append({"n": i, "title": t["title"], "ms": t["ms"], "url": None,
                             "flag": "falhou", "note": str(exc)})
                continue
            if cand is None:
                plan.append({"n": i, "title": t["title"], "ms": t["ms"], "url": None,
                             "flag": "falhou", "note": "nenhum resultado"})
                continue
            dur = f"{int(cand['duration'])}s" if cand.get("duration") else "?"
            plan.append({"n": i, "title": t["title"], "ms": t["ms"], "url": cand["url"],
                         "flag": verdict(score),
                         "note": f"{cand['title']} [{cand['channel']}, {dur}] pontos={score:.0f}"})
    return info, plan, notes


def run_album(yt, artist, album, url, args, report):
    say(f"\n=== {artist} - {album}")
    try:
        info, plan, notes = plan_album(yt, artist, album, url)
    except RuntimeError as exc:
        say(f"   FALHOU: {exc}")
        report.append(f"{artist} - {album}: FALHOU ({exc})")
        return
    year = info["year"] if info else ""
    title = info["title"] if info else album
    total = len(plan)
    if info:
        say(f"   MusicBrainz: '{info['title']}' ({year or 's/ano'}), {len(info['tracks'])} faixas")
    for n in notes:
        say(f"   aviso: {n}")
    report.append(f"{artist} - {album} ({total} faixas)")
    report.extend(f"   aviso: {n}" for n in notes)
    for p in plan:
        mark = {"ok": " ", "semconf": "~"}.get(p["flag"], "!")
        say(f"  {mark} {p['n']:02d} {p['title']}  <-  {p['flag']}: {p['note']}")
        report.append(f"  {p['n']:02d} [{p['flag']}] {p['title']}  <- {p['note']}")
    if args.scan:
        return
    folder = Path(args.out) / safe(artist) / safe(f"{title} ({year})" if year else title)
    folder.mkdir(parents=True, exist_ok=True)
    cover = None
    cover = next(iter(sorted(folder.glob("cover.*"))), None)
    if cover is None and info:
        cover = fetch_cover(info, folder)
    if cover is None:
        first = next((p["url"] for p in plan if p["url"]), None)
        if first:
            cover = yt.fetch_thumb(first, folder)
            if cover:
                say("  capa: usei a miniatura do video (aproximada)")
    done = 0
    for p in plan:
        if not p["url"]:
            continue
        digits = max(2, len(str(total)))
        dst = folder / f"{p['n']:0{digits}d} - {safe(p['title'])}.{args.format}"
        if dst.exists():
            done += 1
            continue
        work = tempfile.mkdtemp(prefix="jgrab-")
        try:
            say(f"  baixando {p['n']:02d} {p['title']} ...")
            raw = yt.download(p["url"], work, args.format)
            meta = {"title": p["title"], "artist": artist, "album_artist": artist,
                    "album": title, "track": f"{p['n']}/{total}"}
            if year:
                meta["date"] = year
            tag_file(raw, dst, meta, cover, args.format)
            done += 1
        except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
            say(f"   FALHOU {p['n']:02d}: {exc}")
            report.append(f"  {p['n']:02d} DOWNLOAD FALHOU: {exc}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    say(f"  -> {done}/{total} faixas em {folder}")
    report.append(f"  -> {done}/{total} faixas em {folder}")


# ------------------------------------------------------------------ cli
def read_list(path):
    items = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            say(f"linha ignorada (use 'Artista | Album'): {line}")
            continue
        items.append((parts[0], parts[1], parts[2] if len(parts) > 2 and parts[2] else None))
    return items


def doctor():
    ok = True
    for exe in ("yt-dlp", "ffmpeg"):
        path = shutil.which(exe)
        say(f"{exe}: {path or 'NAO ENCONTRADO'}")
        ok = ok and bool(path)
    if not ok:
        say("\ninstale: sudo xbps-install -S yt-dlp ffmpeg nodejs")
        return 1
    say("yt-dlp versao: " + subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True).stdout.strip())
    runtimes = [r for r in ("deno", "node", "bun", "qjs") if shutil.which(r)]
    say("runtime JS: " + (", ".join(runtimes) or "NENHUM (o YouTube pode falhar; instale nodejs ou deno)"))
    say("teste de busca no YouTube ...")
    yt = YT()
    try:
        res = yt.search("slipknot wait and bleed", 1)
        say("  ok: " + (res[0]["title"] if res else "sem resultados"))
    except RuntimeError as exc:
        say(f"  FALHOU: {exc}")
        say("  dica: atualize o yt-dlp (pipx install 'yt-dlp[default]') e tenha nodejs/deno instalado")
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="Baixa albuns e confere a ordem das faixas.")
    ap.add_argument("list", nargs="?", default="albums.txt")
    ap.add_argument("--out", default=str(Path.home() / "Musicas"))
    ap.add_argument("--format", choices=("mp3", "m4a"), default="mp3")
    ap.add_argument("--scan", action="store_true", help="so confere, nao baixa")
    ap.add_argument("--only", default="", help="so albuns que contem esse texto")
    ap.add_argument("--doctor", action="store_true")
    ap.add_argument("--no-remote-ejs", action="store_true")
    args = ap.parse_args()

    if args.doctor:
        sys.exit(doctor())
    for exe in ("yt-dlp", "ffmpeg"):
        if not shutil.which(exe):
            sys.exit(f"{exe} nao encontrado. Instale: sudo xbps-install -S yt-dlp ffmpeg nodejs")
    if not Path(args.list).is_file():
        sys.exit(f"lista nao encontrada: {args.list}")
    items = [i for i in read_list(args.list) if args.only.lower() in f"{i[0]} {i[1]}".lower()]
    if not items:
        sys.exit("nenhum album na lista (confira o texto de --only).")

    yt = YT(remote_ejs=not args.no_remote_ejs)
    report = []
    try:
        for artist, album, url in items:
            run_album(yt, artist, album, url, args, report)
    except KeyboardInterrupt:
        say("\ninterrompido.")
    rel = Path(args.list).resolve().with_name("jgrab-relatorio.txt")
    rel.write_text("\n".join(report) + "\n", encoding="utf-8")
    say(f"\nrelatorio salvo em {rel}")
    say("Legenda: ' ' ok | '!' duvida/faltando/falhou (confira) | '~' sem conferencia oficial")


if __name__ == "__main__":
    main()
