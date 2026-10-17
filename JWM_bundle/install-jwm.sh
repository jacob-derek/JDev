#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET=${1:-"$HOME/JDev"}

if [ ! -d "$TARGET" ]; then
    echo "Diretório de destino não existe: $TARGET" >&2
    echo "Uso: $0 /caminho/para/JDev" >&2
    exit 1
fi
if [ ! -f "$TARGET/JDesk.py" ] || [ ! -f "$TARGET/JTerm.py" ]; then
    echo "Não encontrei JDesk.py e JTerm.py em: $TARGET" >&2
    echo "Extraia o pacote e informe o diretório JDev existente." >&2
    exit 1
fi

STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="$TARGET/backups/JWM-before-$STAMP"
mkdir -p "$BACKUP"
for name in JWM.py JRun.py jwm-session start-jwm; do
    if [ -e "$TARGET/$name" ]; then
        cp -p "$TARGET/$name" "$BACKUP/$name"
    fi
    cp "$HERE/$name" "$TARGET/$name"
done
chmod +x "$TARGET/JWM.py" "$TARGET/JRun.py" "$TARGET/jwm-session" "$TARGET/start-jwm"

echo "JWM instalado em: $TARGET"
echo "Backup dos arquivos JWM anteriores: $BACKUP"
echo "Nenhum arquivo JDesk/JTerm/JShell/JCode/JFiles/JBar foi alterado."
echo "Leia: $HERE/README_JWM.md"
