#!/bin/sh
# JDev - corrige a saida analogica do PulseAudio no Void Linux.
set -eu

CARD="${JDEV_AUDIO_CARD:-alsa_card.pci-0000_00_1b.0}"
SINK="${JDEV_AUDIO_SINK:-alsa_output.pci-0000_00_1b.0.analog-stereo}"

aplicar() {
    for i in $(seq 1 10); do
        pactl info >/dev/null 2>&1 && break
        sleep 1
    done

    pactl set-card-profile "$CARD" output:analog-stereo 2>/dev/null || true
    pactl set-default-sink "$SINK" 2>/dev/null || true

    echo "jdev-audio-fix: sink=$SINK profile=analog-stereo"
}

instalar() {
    SCRIPT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/$(basename "$0")"

    mkdir -p "$HOME/.config/autostart"

    cat > "$HOME/.config/autostart/jdev-audio-fix.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=JDev Audio Fix
Comment=Corrige a saida analogica do PulseAudio
Exec=/bin/sh "$SCRIPT" --apply
Terminal=false
X-GNOME-Autostart-enabled=true
DESKTOP

    echo "JDev Audio Fix instalado na inicializacao da sessao grafica."
    echo "Para testar agora: $SCRIPT --apply"
    echo "Para desinstalar: rm ~/.config/autostart/jdev-audio-fix.desktop"
}

case "${1:-}" in
    --apply) aplicar ;;
    --install) instalar ;;
    *)
        echo "Uso: $0 --apply | --install"
        exit 1
        ;;
esac
