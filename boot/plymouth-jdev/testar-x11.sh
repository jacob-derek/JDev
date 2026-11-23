#!/bin/bash
# Executa o tema somente no simulador em /tmp; nao altera o boot do host.
set -Eeuo pipefail

if [[ "${JDEV_TEST_MOUNT_NS:-0}" != 1 ]]; then
    exec unshare -Ur -m /usr/bin/env JDEV_TEST_MOUNT_NS=1 /bin/bash "$0" "$@"
fi

BASE=$(cd -- "$(dirname -- "$0")" && pwd)
SIM=/tmp/void-sim
ROOT="$SIM/root"
THEME="$ROOT/usr/share/plymouth/themes/jdev"
TEST_THEME="${JDEV_TEST_THEME:-jdev}"
DISPLAY_NUM=77
SOCKET="$ROOT/tmp/.X11-unix/X$DISPLAY_NUM"
LOCK="$ROOT/tmp/.X$DISPLAY_NUM-lock"
STAMP=$(date +%Y%m%d-%H%M%S)

if [[ ! -x "$ROOT/usr/bin/plymouthd" || ! -x "$ROOT/usr/bin/Xvfb" ]]; then
    echo "Simulador incompleto em $ROOT; instale plymouth, xorg-server-xvfb, base-files, bash e coreutils nele." >&2
    exit 1
fi
if [[ "$TEST_THEME" != jdev && "$TEST_THEME" != script ]]; then
    echo "JDEV_TEST_THEME aceita somente jdev ou script." >&2
    exit 1
fi
command -v xwd >/dev/null || { echo "xwd nao encontrado no host." >&2; exit 1; }
command -v xwininfo >/dev/null || { echo "xwininfo nao encontrado no host." >&2; exit 1; }
command -v xmessage >/dev/null || { echo "xmessage nao encontrado no host." >&2; exit 1; }

mount --make-rprivate /
mount --rbind /dev "$ROOT/dev"
mount --make-rslave "$ROOT/dev"

mkdir -p "$ROOT/tmp/.X11-unix" "$ROOT/usr/share/plymouth/themes"
if [[ "$TEST_THEME" == jdev ]]; then
  if [[ -d "$THEME" ]]; then
      mv "$THEME" "$SIM/jdev-theme.$STAMP.bak"
  fi
  mkdir -p "$THEME"
  cp -a "$BASE/jdev.plymouth" "$BASE/jdev.script" "$BASE/assets" "$THEME/"
fi

mkdir -p "$ROOT/etc/plymouth"
if [[ -e "$ROOT/etc/plymouth/plymouthd.conf" ]]; then
    cp -a "$ROOT/etc/plymouth/plymouthd.conf" "$SIM/plymouthd.conf.$STAMP.bak"
fi
cat > "$ROOT/etc/plymouth/plymouthd.conf" <<EOF
[Daemon]
Theme=$TEST_THEME
Renderer=x11
ShowDelay=0
DeviceTimeout=5
EOF

for output in "$SIM/xvfb.log" "$SIM/plymouthd.log" "$SIM/xmessage.log" "$SIM/tema-$TEST_THEME.xwd" "$SIM/tema-$TEST_THEME.png" "$SIM/xwininfo-$TEST_THEME.txt" "$SIM/x11-probe.xwd" "$SIM/x11-probe.png" "$SIM/xwininfo-probe.txt" "$ROOT/tmp/jdev-debug.log"; do
    [[ ! -e "$output" ]] || mv "$output" "$output.$STAMP.bak"
done

if [[ -S "$SOCKET" || -f "$LOCK" ]]; then
    live_pid=
    if [[ -f "$LOCK" ]]; then
        read -r live_pid < "$LOCK" || true
    fi
    if [[ -n "$live_pid" ]] && kill -0 "$live_pid" 2>/dev/null; then
        echo "Display :$DISPLAY_NUM ja esta ativo (PID $live_pid); pare-o antes de repetir." >&2
        exit 1
    fi
    [[ ! -e "$SOCKET" ]] || mv "$SOCKET" "$SIM/X$DISPLAY_NUM.socket.$STAMP.bak"
    [[ ! -e "$LOCK" ]] || mv "$LOCK" "$SIM/X$DISPLAY_NUM.lock.$STAMP.bak"
fi

HOST_SOCKET="/tmp/.X11-unix/X$DISPLAY_NUM"
if [[ -L "$HOST_SOCKET" ]]; then
    [[ "$(readlink "$HOST_SOCKET")" == "$SOCKET" ]] || {
        echo "O link $HOST_SOCKET aponta para outro destino; parei sem toca-lo." >&2
        exit 1
    }
elif [[ -e "$HOST_SOCKET" ]]; then
    echo "Existe um socket X alheio em $HOST_SOCKET; parei sem toca-lo." >&2
    exit 1
else
    ln -s "$SOCKET" "$HOST_SOCKET"
fi

xvfb_pid=
plymouth_pid=
probe_pid=
cleanup() {
    [[ -z "$probe_pid" ]] || kill "$probe_pid" 2>/dev/null || true
    chroot "$ROOT" /usr/bin/plymouth --quit >/dev/null 2>&1 || true
    [[ -z "$plymouth_pid" ]] || kill "$plymouth_pid" 2>/dev/null || true
    [[ -z "$xvfb_pid" ]] || kill "$xvfb_pid" 2>/dev/null || true
    [[ -z "$probe_pid" ]] || wait "$probe_pid" 2>/dev/null || true
    [[ -z "$plymouth_pid" ]] || wait "$plymouth_pid" 2>/dev/null || true
    [[ -z "$xvfb_pid" ]] || wait "$xvfb_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

chroot "$ROOT" /usr/bin/Xvfb ":$DISPLAY_NUM" -screen 0 1280x720x24 -nolisten tcp -ac \
    >"$SIM/xvfb.log" 2>&1 &
xvfb_pid=$!
sleep 2
kill -0 "$xvfb_pid" || { cat "$SIM/xvfb.log"; exit 1; }

chroot "$ROOT" /usr/bin/env DISPLAY=":$DISPLAY_NUM" \
    /usr/bin/plymouthd --no-daemon --debug --debug-file=/tmp/jdev-debug.log \
    --mode=boot --tty=/dev/tty --kernel-command-line="quiet splash" \
    >"$SIM/plymouthd.log" 2>&1 &
plymouth_pid=$!
sleep 2
if ! chroot "$ROOT" /usr/bin/plymouth --ping; then
    echo "plymouthd nao respondeu; logs abaixo:" >&2
    cat "$SIM/plymouthd.log" "$ROOT/tmp/jdev-debug.log" 2>/dev/null || true
    exit 1
fi

chroot "$ROOT" /usr/bin/plymouth --show-splash
sleep 2
chroot "$ROOT" /usr/bin/plymouth --update=udev
sleep 4

xwininfo -display ":$DISPLAY_NUM" -root -tree > "$SIM/xwininfo-$TEST_THEME.txt"
window_id=$(sed -n 's/^[[:space:]]*\(0x[[:xdigit:]]\+\).*/\1/p' "$SIM/xwininfo-$TEST_THEME.txt" | head -1)
if [[ -z "$window_id" ]]; then
    echo "Nenhuma janela filha do Plymouth no Xvfb:" >&2
    cat "$SIM/xwininfo-$TEST_THEME.txt" >&2
    exit 1
fi
xwd -display ":$DISPLAY_NUM" -id "$window_id" -out "$SIM/tema-$TEST_THEME.xwd"
python3 "$BASE/xwd_to_png.py" "$SIM/tema-$TEST_THEME.xwd" "$SIM/tema-$TEST_THEME.png"
echo "Janela capturada: $window_id"
echo "Log Plymouth: $ROOT/tmp/jdev-debug.log"
echo "Screenshot: $SIM/tema-$TEST_THEME.png"

chroot "$ROOT" /usr/bin/plymouth --quit >/dev/null 2>&1 || true
wait "$plymouth_pid" 2>/dev/null || true
plymouth_pid=
xmessage -display ":$DISPLAY_NUM" -title "JDev X11 Probe" -buttons OK:0 "Teste de captura X11" \
    >"$SIM/xmessage.log" 2>&1 &
probe_pid=$!
sleep 2
xwininfo -display ":$DISPLAY_NUM" -name "JDev X11 Probe" > "$SIM/xwininfo-probe.txt"
probe_id=$(sed -n 's/.*Window id: \(0x[[:xdigit:]]\+\).*/\1/p' "$SIM/xwininfo-probe.txt" | head -1)
if [[ -z "$probe_id" ]]; then
    echo "Janela de teste X11 nao encontrada:" >&2
    cat "$SIM/xwininfo-probe.txt" "$SIM/xmessage.log" >&2
    exit 1
fi
xwd -display ":$DISPLAY_NUM" -id "$probe_id" -out "$SIM/x11-probe.xwd"
python3 "$BASE/xwd_to_png.py" "$SIM/x11-probe.xwd" "$SIM/x11-probe.png"
echo "Captura de controle: $SIM/x11-probe.png"
