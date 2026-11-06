#!/bin/sh
# Testa o JWM dentro de uma janela (Xephyr), sem arriscar a sessão real.
#
#   scripts/xephyr-test.sh              JWM completo (JDesk + JBar)
#   scripts/xephyr-test.sh --no-ui      só o gerenciador de janelas
#
# Precisa de: Xephyr (Void: xbps-install xorg-server-xephyr) e python-xlib.
# Rode de dentro de uma sessão X. Feche a janela do Xephyr para encerrar tudo.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if ! command -v Xephyr >/dev/null 2>&1; then
    echo "Xephyr não encontrado (Void: sudo xbps-install xorg-server-xephyr)." >&2
    exit 1
fi
if [ -z "${DISPLAY:-}" ]; then
    echo "Rode de dentro de uma sessão X (precisa de \$DISPLAY)." >&2
    exit 1
fi

N=2
while [ -e "/tmp/.X11-unix/X$N" ]; do
    N=$((N + 1))
done
TELA=${TELA:-1280x720}

Xephyr ":$N" -screen "$TELA" -ac -br >/dev/null 2>&1 &
XEPHYR_PID=$!
trap 'kill "$XEPHYR_PID" 2>/dev/null || true' EXIT INT TERM
sleep 1

echo "JWM em Xephyr :$N ($TELA). Feche a janela do Xephyr para sair."
DISPLAY=":$N" python3 "$HERE/JWM.py" "$@"
