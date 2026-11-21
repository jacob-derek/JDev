"""jrcore - núcleo do JRun sem tela: ler .desktop, buscar/ordenar, histórico de uso, cache, trava, calculadora."""
from __future__ import annotations

import ast
import configparser
import json
import operator
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

JTERM = Path(__file__).resolve().parent / "JTerm.py"


# ── .desktop ─────────────────────────────────────────────────────────────────
def pastas_de_aplicativos() -> list[str]:
    dirs = [os.path.expanduser("~/.local/share/applications"),
            os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
            "/var/lib/flatpak/exports/share/applications",
            "/usr/local/share/applications", "/usr/share/applications",
            os.path.expanduser("~/.nix-profile/share/applications")]
    for base in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        if base:
            dirs.append(os.path.join(base, "applications"))
    out, vistos = [], set()
    for p in dirs:
        p = os.path.abspath(os.path.expanduser(p))
        if p not in vistos and os.path.isdir(p):
            out.append(p)
            vistos.add(p)
    return out


def limpar_argv(comando: str) -> list[str] | None:
    """Exec= de um .desktop -> argv sem os códigos de campo (%U, %f, --arg=%c...). None se inválido."""
    try:
        bruto = shlex.split(comando)
    except ValueError:
        return None
    argv = []
    for a in bruto:
        limpo = re.sub(r"%[A-Za-z]", "", a.replace("%%", "\0")).replace("\0", "%")
        if limpo or not a:
            argv.append(limpo)
    return argv or None


def ler_aplicativos(pastas=None) -> list[dict]:
    """Lançadores .desktop visíveis cujo executável existe. O 1º diretório vence em nomes repetidos."""
    apps = {}
    for diretorio in (pastas if pastas is not None else pastas_de_aplicativos()):
        for atual, subs, arquivos in os.walk(diretorio):
            subs[:] = [d for d in subs if d not in (".", "locale")]
            for nome_arq in arquivos:
                if not nome_arq.endswith(".desktop") or nome_arq in apps:
                    continue
                caminho = os.path.join(atual, nome_arq)
                cfg = configparser.ConfigParser(interpolation=None, strict=False)
                cfg.optionxform = str
                try:
                    cfg.read(caminho, encoding="utf-8")
                    sec = cfg["Desktop Entry"]
                    if sec.get("Type", "Application") != "Application":
                        continue
                    if sec.get("Hidden", "false").lower() == "true" or sec.get("NoDisplay", "false").lower() == "true":
                        continue
                    nome, comando = sec.get("Name", "").strip(), sec.get("Exec", "").strip()
                    argv = limpar_argv(comando) if comando else None
                    if not nome or not argv:
                        continue
                    tentar = sec.get("TryExec", "").strip()
                    if tentar and not (os.path.isabs(tentar) and os.path.exists(tentar) or shutil.which(tentar)):
                        continue
                    exe = argv[0]
                    if not (os.path.isabs(exe) and os.path.exists(exe) or shutil.which(exe)):
                        continue
                    apps[nome_arq] = {
                        "id": nome_arq, "name": nome, "exec": comando, "argv": argv,
                        "comment": sec.get("Comment", "").strip(),
                        "categories": sec.get("Categories", "").replace(";", " · ").strip(" ·"),
                        "path": caminho, "terminal": sec.get("Terminal", "false").lower() == "true",
                        "cwd": sec.get("Path", "").strip(),
                    }
                except (OSError, KeyError, configparser.Error, UnicodeError):
                    continue
    return sorted(apps.values(), key=lambda a: a["name"].casefold())


# ── busca e ordem ────────────────────────────────────────────────────────────
def _pontos_palavra(app: dict, q: str) -> int | None:
    nome = app["name"].casefold()
    if nome == q:
        return 100
    if nome.startswith(q):
        return 90
    if any(p.startswith(q) for p in re.split(r"[\s\-_.]+", nome) if p):
        return 75
    if q in nome:
        return 60
    if len(q) >= 2:
        i = 0
        for c in nome:
            if i < len(q) and c == q[i]:
                i += 1
        if i == len(q):
            return 40
    if app.get("argv") and q in os.path.basename(app["argv"][0]).casefold():
        return 30
    if q in app.get("comment", "").casefold():
        return 20
    if q in app.get("categories", "").casefold():
        return 10
    return None


def pontuar(app: dict, consulta: str) -> int | None:
    """Todas as palavras da consulta precisam casar; vale a pior delas. Sem consulta: 0."""
    palavras = consulta.casefold().split()
    if not palavras:
        return 0
    notas = [_pontos_palavra(app, p) for p in palavras]
    return None if any(n is None for n in notas) else min(notas)


def buscar(apps: list[dict], consulta: str, uso: dict[str, int] | None = None) -> list[dict]:
    """Casa, ordena por relevância e, no empate, pelo que você mais abre; sem consulta: mais usados primeiro."""
    uso = uso or {}
    achados = []
    for a in apps:
        p = pontuar(a, consulta)
        if p is not None:
            achados.append((p, uso.get(a.get("id", ""), 0), a))
    achados.sort(key=lambda t: (-t[0], -t[1], t[2]["name"].casefold()))
    return [a for _, _, a in achados]


# ── histórico de uso e cache (JSON, gravação atômica) ────────────────────────
def _base(env: str, padrao: str) -> Path:
    return Path(os.environ.get(env) or Path.home() / padrao) / "jdev"


def arquivo_uso() -> Path:
    return _base("XDG_STATE_HOME", ".local/state") / "jrun-uso.json"


def arquivo_cache() -> Path:
    return _base("XDG_CACHE_HOME", ".cache") / "jrun-apps.json"


def _ler_json(arq, padrao):
    try:
        return json.loads(Path(arq).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def _gravar_json(arq, dados) -> None:
    arq = Path(arq)
    try:
        arq.parent.mkdir(parents=True, exist_ok=True)
        tmp = arq.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, arq)
    except OSError:
        pass


def uso_ler(arq=None) -> dict[str, int]:
    d = _ler_json(arq or arquivo_uso(), {})
    return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, int)} if isinstance(d, dict) else {}


def uso_registrar(id_app: str, arq=None, limite: int = 500) -> None:
    arq = arq or arquivo_uso()
    d = uso_ler(arq)
    d[id_app] = d.get(id_app, 0) + 1
    if len(d) > limite:
        for k, _ in sorted(d.items(), key=lambda kv: kv[1])[: len(d) - limite]:
            d.pop(k)
    _gravar_json(arq, d)


CHAVES = ("id", "name", "exec", "argv", "comment", "categories", "path", "terminal", "cwd")


def cache_ler(arq=None) -> list[dict]:
    d = _ler_json(arq or arquivo_cache(), {})
    apps = d.get("apps") if isinstance(d, dict) else None
    if not isinstance(apps, list):
        return []
    return [a for a in apps if isinstance(a, dict) and all(k in a for k in CHAVES) and isinstance(a["argv"], list)]


def cache_gravar(apps: list[dict], arq=None) -> None:
    _gravar_json(arq or arquivo_cache(), {"apps": apps})


# ── instância única ──────────────────────────────────────────────────────────
def instancia_viva(lock, marca: str = "JRun") -> bool:
    """True se o lockfile aponta para um processo VIVO que é mesmo o JRun (pid reaproveitado não conta)."""
    try:
        pid = int(Path(lock).read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    try:
        return marca.lower() in Path(f"/proc/{pid}/cmdline").read_text(errors="replace").lower()
    except OSError:
        return True      # sem /proc (não-Linux): confia no kill


# ── comandos digitados ───────────────────────────────────────────────────────
_META = set("|&;<>$*?(){}`~\\")


def argv_do_comando(texto: str) -> list[str] | None:
    """Texto digitado -> argv. Com pipe, $VAR, redirecionamento etc. (ou prefixo '!'/'>'), roda no sh -c."""
    t = texto.strip()
    if t[:1] in ("!", ">"):
        t = t[1:].strip()
        return ["sh", "-c", t] if t else None
    if not t:
        return None
    if _META & set(t):
        return ["sh", "-c", t]
    try:
        return shlex.split(t) or None
    except ValueError:
        return ["sh", "-c", t]


def argv_terminal(argv: list[str], which=shutil.which) -> list[str] | None:
    """Embrulha `argv` num terminal: o JTerm do JDev se existir; senão o primeiro conhecido (com -e)."""
    if JTERM.exists():
        return [sys.executable, str(JTERM), *argv]
    for t in ("x-terminal-emulator", "xterm", "urxvt", "kitty", "alacritty", "foot"):
        achado = which(t)
        if achado:
            return [achado, "-e", *argv]
    return None


# ── calculadora (digite "=2*(3+4)") ──────────────────────────────────────────
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def _avaliar(no):
    if isinstance(no, ast.Expression):
        return _avaliar(no.body)
    if isinstance(no, ast.Constant) and isinstance(no.value, (int, float)) and not isinstance(no.value, bool):
        return no.value
    if isinstance(no, ast.BinOp) and type(no.op) in _OPS:
        a, b = _avaliar(no.left), _avaliar(no.right)
        if isinstance(no.op, ast.Pow) and (abs(b) > 100 or abs(a) > 1e6):
            raise ValueError("potência grande demais")
        return _OPS[type(no.op)](a, b)
    if isinstance(no, ast.UnaryOp) and type(no.op) in _OPS:
        return _OPS[type(no.op)](_avaliar(no.operand))
    raise ValueError("expressão não permitida")


def calcular(texto: str) -> str | None:
    """'=2+2' -> '4'. Só números e + - * / // % ** ( ); qualquer outra coisa (ou erro) -> None."""
    t = texto.strip()
    if not t.startswith("=") or len(t) < 2 or len(t) > 200:
        return None
    try:
        v = _avaliar(ast.parse(t[1:].replace(",", ".").strip(), mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError, MemoryError):
        return None
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v)
