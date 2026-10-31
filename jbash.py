#!/usr/bin/env python3
"""
jbash - motor bash do JShell.

O JShell cuida da cara (prompt, cores, completion, comandos bonitos); quem EXECUTA é um
bash de verdade, vivo durante toda a sessão. Por isso funcionam, sem o JShell reimplementar
nada: source, alias do ~/.bashrc, funções, variáveis, $(...), &&/||, here-doc, for/while/if,
export, set, trap, completions do bash-completion (git, xbps...), zoxide/direnv/nvm etc.

Como funciona
  * `bash -i` lê os comandos de um pipe (não do teclado). Cada comando roda dentro de
    `{ ...; } <&TTY 2>&TTY`, então programas interativos (vim, htop, ssh, read) usam o terminal
    de verdade, e stdout/stderr vão direto para a tela.
  * O stderr do próprio bash é um pty privado (log em ~/.cache/jshell/motor.err): assim ele não
    tem terminal de controle e NÃO toma o terminal do JShell (sem controle de jobs).
  * Depois de cada comando o JShell manda `__jsh_fim`, que avisa por outro pipe que acabou,
    com: código de saída, diretório atual, nomes de aliases/funções e o ambiente (env).
    O PROMPT_COMMAND do usuário (zoxide, direnv...) continua rodando normalmente.
  * Ctrl+C: o bash interativo aborta a linha e volta ao prompt (a sessão sobrevive).
  * Sem bash (ou se algo falhar) `Motor.iniciar()` devolve False e o JShell cai no
    comportamento antigo: cada programa continua funcionando sozinho.

Roda sozinho para teste:  python3 jbash.py 'echo oi; cd /tmp; pwd'
"""
from __future__ import annotations

import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REG_INI, SEP, REG_FIM = b"\x1e", b"\x1f", b"\x1d"

# Linha "simples" (só palavras): dispensa a checagem de sintaxe com `bash -n`.
_PLANA = re.compile(r"[\w@%+=:,./~ -]+")
_COMPOSTAS = {"if", "for", "while", "until", "case", "select", "function", "{", "[[", "time", "coproc", "!"}

INIT = r'''# jbash - init do motor bash do JShell (arquivo gerado; edições aqui são sobrescritas)
shopt -s expand_aliases checkwinsize 2>/dev/null
set +H
bind() { :; }                                   # bashrc costuma chamar bind; aqui não há readline
if [ -z "${JSH_SEM_BASHRC:-}" ]; then
  for __f in /etc/bash.bashrc /etc/bash/bashrc "$HOME/.bashrc"; do
    [ -r "$__f" ] && . "$__f"
  done
  unset __f
fi
[ -r "$HOME/.jshellrc" ] && . "$HOME/.jshellrc"
unset -f bind
set +o history 2>/dev/null
HISTFILE=/dev/null
PS1='' PS2='' PS4='+ '

# completions programáveis (git, xbps, ssh...) se o bash-completion ainda não foi carregado
if ! declare -F _completion_loader >/dev/null 2>&1 && ! declare -F _comp_load >/dev/null 2>&1; then
  [ -r /usr/share/bash-completion/bash_completion ] && . /usr/share/bash-completion/bash_completion 2>/dev/null
fi

# atalhos padrão do JShell (só se você não tiver os seus)
alias .. >/dev/null 2>&1 || alias ..='cd ..'
alias ... >/dev/null 2>&1 || alias ...='cd ../..'

# ── ganchos e aviso de fim de comando ────────────────────────────────────────
# PROMPT_COMMAND roda os ganchos do usuário (zoxide, direnv...). O aviso de "terminei" NÃO
# depende dele: o JShell manda `__jsh_fim` depois de cada comando, então reatribuir
# PROMPT_COMMAND dentro da sessão não trava nada.
__jsh_pc_user=("${PROMPT_COMMAND[@]}")
__jsh_prompt() {
  local __st=$? __pc
  if [ -z "${__jsh_quiet:-}" ]; then
    for __pc in "${__jsh_pc_user[@]}"; do
      [ -n "$__pc" ] || continue
      (exit "$__st")
      eval "$__pc"
    done
  fi
  unset __jsh_quiet
  return "$__st"
}
PROMPT_COMMAND=__jsh_prompt
# Se algo reatribuir PROMPT_COMMAND na sessão (source ~/.bashrc, starship...), adota o valor
# como novos ganchos do usuário e reinstala o nosso, para não repetir ganchos nem imprimir
# durante completions.
__jsh_adota_pc() {
  [[ "${PROMPT_COMMAND[*]}" == "__jsh_prompt" ]] && return 0
  local x tinha=0; local -a novos=()
  [[ "${PROMPT_COMMAND[*]}" == *__jsh_prompt* ]] && tinha=1   # acrescentou em volta do nosso
  for x in "${PROMPT_COMMAND[@]}"; do
    x=${x//__jsh_prompt/:}
    [[ -n $x && $x != : ]] && novos+=("$x")
  done
  if (( tinha )); then __jsh_pc_user+=("${novos[@]}"); else __jsh_pc_user=("${novos[@]}"); fi
  PROMPT_COMMAND=__jsh_prompt
}
__jsh_fim() {
  local __st=$? __seq=${1:-0}
  __jsh_adota_pc
  {
    printf '\036S\037%s\037%s\037%s\037' "$__seq" "$__st" "$PWD"
    compgen -a | tr '\n' ' '
    printf '\037'
    compgen -A function | tr '\n' ' '
    printf '\037'
    env -0
    printf '\035'
  } >&"$JSH_ST_FD" 2>/dev/null
  __jsh_quiet=1          # o gancho que roda depois deste comando não deve repetir os do usuário
  return "$__st"
}

# ── completion programável ───────────────────────────────────────────────────
# __jsh_cap: lê um "complete ..." e guarda -F/-W/-A/-o em variáveis
__jsh_cap() {
  __jc_F= __jc_W= __jc_A= __jc_o=
  local OPTIND=1 o
  while getopts 'abcdefgjksuvA:C:DEF:G:IW:o:P:S:X:' o; do
    case $o in
      F) __jc_F=$OPTARG ;;
      W) __jc_W=$OPTARG ;;
      A) __jc_A="$__jc_A $OPTARG" ;;
      o) __jc_o="$__jc_o $OPTARG" ;;
      a) __jc_A="$__jc_A alias" ;;  b) __jc_A="$__jc_A builtin" ;;
      c) __jc_A="$__jc_A command" ;; d) __jc_A="$__jc_A directory" ;;
      e) __jc_A="$__jc_A export" ;;  f) __jc_A="$__jc_A file" ;;
      g) __jc_A="$__jc_A group" ;;   j) __jc_A="$__jc_A job" ;;
      k) __jc_A="$__jc_A keyword" ;; s) __jc_A="$__jc_A service" ;;
      u) __jc_A="$__jc_A user" ;;    v) __jc_A="$__jc_A variable" ;;
    esac
  done
}
# uso: __jsh_complete "linha até o cursor" CWORD palavra0 palavra1 ...
__jsh_complete() {
  local COMP_LINE=$1 cword=$2; shift 2
  local -a COMP_WORDS=("$@") COMPREPLY=()
  local COMP_CWORD=$cword COMP_POINT=${#COMP_LINE} COMP_TYPE=9 COMP_KEY=9
  local cmd=${COMP_WORDS[0]} cur=${COMP_WORDS[cword]-} prev= spec tries=0 rc
  (( cword > 0 )) && prev=${COMP_WORDS[cword-1]}
  local __jc_F __jc_W __jc_A __jc_o
  while (( tries++ < 3 )); do
    spec=$(complete -p -- "$cmd" 2>/dev/null)
    if [[ -z $spec ]]; then
      if declare -F _comp_load >/dev/null 2>&1; then _comp_load -- "$cmd" >/dev/null 2>&1
      elif declare -F _completion_loader >/dev/null 2>&1; then _completion_loader "$cmd" >/dev/null 2>&1; fi
      spec=$(complete -p -- "$cmd" 2>/dev/null)
    fi
    [[ -n $spec ]] || break
    eval "__jsh_cap ${spec#complete}"
    COMPREPLY=()
    if [[ -n $__jc_F ]]; then
      "$__jc_F" "$cmd" "$cur" "$prev" >/dev/null 2>&1; rc=$?
      (( rc == 124 )) && continue
    fi
    [[ -n $__jc_W ]] && COMPREPLY+=( $(compgen -W "$__jc_W" -- "$cur") )
    local a
    for a in $__jc_A; do COMPREPLY+=( $(compgen -A "$a" -- "$cur") ); done
    break
  done
  {
    printf '\036C\037%s\037' "$__jc_o"
    (( ${#COMPREPLY[@]} )) && printf '%s\0' "${COMPREPLY[@]}"
    printf '\035'
  } >&"$JSH_ST_FD"
}
'''


class Motor:
    """Um bash persistente. Todas as chamadas públicas são seguras para threads."""

    def __init__(self, bashrc: bool = True):
        self.bashrc = bashrc
        self.proc = None
        self.lock = threading.RLock()
        self.status = 0
        self.cwd = None
        self.aliases: set = set()
        self.funcoes: set = set()
        self.nativos: set = set()      # builtins + palavras reservadas do bash
        self._cmd_w = self._st_r = self._tty = self._err_m = None
        self._buf = b""
        self._sujo = False             # uma completion rodou: o próximo comando restaura o $?
        self._seq = 0                  # numera cada "terminei": respostas atrasadas são descartadas
        self._int_t = None             # quando o Ctrl+C chegou durante a espera
        self._ok_texto = None          # último texto já validado por `bash -n`
        self.ultimo_erro = ""

    # ── ciclo de vida ──────────────────────────────────────────────────────
    @staticmethod
    def bash_path():
        return shutil.which("bash")

    def disponivel(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def iniciar(self) -> bool:
        with self.lock:
            self._fechar_fds()
            bash = self.bash_path()
            if not bash:
                self.ultimo_erro = "bash não encontrado"
                return False
            try:
                init = self._gravar_init()
                cmd_r, self._cmd_w = os.pipe()
                self._st_r, st_w = os.pipe()
                self._tty = os.dup(0)
                # O bash `-i` assume o terminal de que é dono (controle de jobs) e o JShell perderia
                # o teclado (Stopped / EIO no prompt_toolkit). Com um pty PRIVADO no stderr ele não
                # tem terminal de controle para tomar. Os comandos escrevem no terminal real por
                # `2>&TTY` (ver executar), e o que o próprio bash escrever aqui vai para o log.
                self._err_m, err_s = os.openpty()
                env = dict(os.environ)
                env.update(JSH_TTY_FD=str(self._tty), JSH_ST_FD=str(st_w), JSHELL="1")
                if not self.bashrc:
                    env["JSH_SEM_BASHRC"] = "1"
                self.proc = subprocess.Popen(
                    [bash, "--noediting", "--rcfile", str(init), "-i", "+m"],
                    stdin=cmd_r, stderr=err_s, pass_fds=(self._tty, st_w), env=env,
                )
                os.close(cmd_r)
                os.close(st_w)
                os.close(err_s)
                threading.Thread(target=self._drenar, args=(self._err_m,), daemon=True).start()
                self._buf = b""
                self._seq = 0
                os.write(self._cmd_w, b"__jsh_fim 0\n")   # 1º aviso: o rc terminou
            except OSError as e:
                self.ultimo_erro = str(e)
                self._fechar_fds()
                self.proc = None
                return False
            self.nativos = self._nomes_nativos(bash)
            ok = self._aguardar("S", 0) is not None
            if not ok:
                self.ultimo_erro = "o bash não respondeu ao iniciar"
            return ok

    @staticmethod
    def _drenar(fd):
        """Esvazia o stderr privado do bash num log (o pty encheria e travaria o bash)."""
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "jshell"
        total = 0
        try:
            with open(base / "motor.err", "wb", buffering=0) as f:
                while True:
                    dado = os.read(fd, 4096)
                    if not dado:
                        break
                    if total < 65536:
                        f.write(dado)
                        total += len(dado)
        except OSError:
            pass

    @staticmethod
    def _gravar_init() -> Path:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "jshell"
        base.mkdir(parents=True, exist_ok=True)
        arq = base / "init.bash"
        if not arq.exists() or arq.read_text(encoding="utf-8") != INIT:
            arq.write_text(INIT, encoding="utf-8")
        return arq

    @staticmethod
    def _nomes_nativos(bash) -> set:
        try:
            out = subprocess.run([bash, "-c", "compgen -b; compgen -k"], capture_output=True,
                                 text=True, timeout=2).stdout
            return set(out.split())
        except (OSError, subprocess.SubprocessError):
            return set()

    def _fechar_fds(self):
        for nome in ("_cmd_w", "_st_r", "_tty", "_err_m"):
            fd = getattr(self, nome)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, nome, None)

    def fechar(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                try:
                    os.write(self._cmd_w, b"exit\n")
                    self.proc.wait(timeout=1)
                except (OSError, subprocess.SubprocessError):
                    self.proc.kill()
            self.proc = None
            self._fechar_fds()

    # ── protocolo ──────────────────────────────────────────────────────────
    def _aguardar(self, tipo, seq=None, coletar=None):
        """Lê registros do pipe de estado até chegar o do `tipo` ('S' = fim de comando) com o
        número `seq`. Registros de outros tipos vão para `coletar`; 'S' de outro número é lixo
        de um comando anterior e é descartado. None se o bash morreu.
        Depois de um Ctrl+C sem resposta em 0,6 s (aspa aberta que escapou da checagem, por
        exemplo), reenvia o aviso: o bash já abortou a leitura pendente e volta ao prompt."""
        reenviado = False
        while True:
            ini = self._buf.find(REG_INI)
            fim = self._buf.find(REG_FIM, ini + 1) if ini >= 0 else -1
            if ini >= 0 and fim >= 0:
                reg = self._buf[ini + 1:fim]
                self._buf = self._buf[fim + 1:]
                if reg[:1] == tipo.encode():
                    corpo = reg[2:]
                    if tipo == "S" and seq is not None:
                        num, _, corpo = corpo.partition(SEP)
                        if num != str(seq).encode():
                            continue
                    return corpo
                if coletar is not None:
                    coletar.append(reg)
                continue
            if self.proc is None or self.proc.poll() is not None:
                return None
            if (self._int_t is not None and not reenviado and seq is not None
                    and time.monotonic() - self._int_t > 0.6):
                reenviado = True
                try:
                    os.write(self._cmd_w, f"\n__jsh_fim {seq}\n".encode())
                except OSError:
                    return None
            pronto, _, _ = select.select([self._st_r], [], [], 0.2)
            if pronto:
                try:
                    dado = os.read(self._st_r, 65536)
                except OSError:
                    return None
                if not dado:
                    return None
                self._buf += dado

    def _aplicar_estado(self, reg: bytes) -> int:
        partes = reg.split(SEP, 3)
        if len(partes) < 4:
            return self.status
        st, pwd, nomes_a, resto = partes
        nomes_f, _, env = resto.partition(SEP)
        try:
            self.status = int(st)
        except ValueError:
            self.status = 1
        self.cwd = pwd.decode(errors="replace")
        self.aliases = set(nomes_a.decode(errors="replace").split())
        self.funcoes = set(nomes_f.decode(errors="replace").split())
        self._aplicar_ambiente(env)
        return self.status

    def _aplicar_ambiente(self, bloco: bytes):
        novo = {}
        for item in bloco.split(b"\0"):
            k, sep, v = item.partition(b"=")
            if sep and k:
                novo[k.decode(errors="replace")] = v.decode(errors="replace")
        if not novo:
            return
        for k in list(os.environ):
            if k not in novo:
                del os.environ[k]
        os.environ.update(novo)
        try:
            if self.cwd and os.path.isdir(self.cwd) and os.getcwd() != self.cwd:
                os.chdir(self.cwd)
        except OSError:
            pass

    # ── API ────────────────────────────────────────────────────────────────
    def executar(self, texto: str):
        """Roda `texto` (uma ou várias linhas) no bash. Devolve o código de saída,
        ou None se o motor não está disponível."""
        with self.lock:
            if not self.disponivel() and not self.iniciar():
                return None
            # rede de segurança: sintaxe incompleta deixaria o bash esperando mais entrada
            primeira = texto.split(None, 1)[0] if texto.split() else ""
            if texto != self._ok_texto and (not _PLANA.fullmatch(texto) or primeira in _COMPOSTAS
                                           or texto.endswith("\\")):
                estado, msg = self.checar(texto)
                if estado != "ok":
                    sys.stderr.write((msg or "erro de sintaxe") + "\n")
                    self.status = 2
                    return 2
            self._ok_texto = None
            pre = f"(exit {self.status})\n" if self._sujo else ""
            self._sujo = False
            self._seq += 1
            seq = self._seq
            carga = "{\n" + pre + texto + "\n} <&" + str(self._tty) + " 2>&" + str(self._tty) + f"\n__jsh_fim {seq}\n"
            sys.stdout.flush()
            sys.stderr.flush()
            self._int_t = None
            velho = None
            try:
                velho = signal.signal(signal.SIGINT, lambda *_: setattr(self, "_int_t", time.monotonic()))
            except ValueError:  # fora da thread principal
                pass
            try:
                os.write(self._cmd_w, carga.encode("utf-8", "surrogateescape"))
                reg = self._aguardar("S", seq)
            except OSError:
                reg = None
            finally:
                if velho is not None:
                    signal.signal(signal.SIGINT, velho)
            if reg is None:  # o bash morreu (exec, kill $$...): reinicia limpo
                self.status = 1
                self.proc = None
                self.iniciar()
                return 1
            return self._aplicar_estado(reg)

    def checar(self, texto: str):
        """Sintaxe do texto: ('ok'|'incompleto'|'erro', mensagem). Usa `bash -n`."""
        bash = self.bash_path()
        if not bash:
            return "ok", ""
        try:
            r = subprocess.run([bash, "-n", "-c", texto], capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            return "ok", ""
        msg = (r.stderr or "").strip()
        if r.returncode == 0 and "here-document" not in msg:
            self._ok_texto = texto
            return "ok", ""
        baixo = msg.lower()
        if "unexpected end of file" in baixo or "unexpected eof" in baixo or "here-document" in baixo:
            return "incompleto", msg
        return "erro", msg

    def completar(self, linha: str, palavras: list, cword: int):
        """Completion programável do bash. Devolve (opções, candidatos)."""
        with self.lock:
            if not self.disponivel() or not palavras:
                return set(), []
            args = " ".join(shlex.quote(p) for p in palavras)
            self._seq += 1
            seq = self._seq
            carga = (f"__jsh_quiet=1; __jsh_complete {shlex.quote(linha)} {int(cword)} {args}\n"
                     f"__jsh_fim {seq}\n")
            coletados = []
            self._int_t = None
            try:
                os.write(self._cmd_w, carga.encode("utf-8", "surrogateescape"))
                fim = self._aguardar("S", seq, coletados)
            except OSError:
                return set(), []
            if fim is None:
                return set(), []
            self._sujo = True
            for reg in coletados:
                if reg[:1] == b"C":
                    corpo = reg[2:]
                    opts, _, lista = corpo.partition(SEP)
                    cands = [c.decode(errors="replace") for c in lista.split(b"\0") if c]
                    return set(opts.decode().split()), cands
            return set(), []

    def conhece(self, nome: str) -> bool:
        """`nome` é alias/função do bash (o bash deve tratar, não o JShell)?"""
        return nome in self.aliases or nome in self.funcoes


def main(argv):
    m = Motor()
    if not m.iniciar():
        print("falhou:", m.ultimo_erro)
        return 1
    codigo = 0
    for linha in argv or ["echo jbash ok"]:
        codigo = m.executar(linha)
    print(f"[status {codigo} · cwd {m.cwd} · aliases {len(m.aliases)} · funções {len(m.funcoes)}]")
    m.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
