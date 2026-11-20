## JFiles repaginado
- Visual novo: pílulas como a JBar/JCode, ícone por tipo de arquivo, marcas do git (● + - ?), tamanho/data, preview à direita.
- Ctrl+L: ir para QUALQUER caminho (Tab completa; texto solto como "dev" pula para pasta recente).
- `/` filtra digitando; Espaço marca vários; c/x/p copiar, recortar, colar; Del apaga (lixeira se houver gio/trash-put).
- `!` roda comando no shell ("$@" = marcados); `d` arrasta para fora (ripdrag/dragon); `y` copia caminho; mouse (clique, scroll).
- Modo seletor: `JFiles.py --pick [--multiple] [--dir] [--save NOME] --out ARQ` + `jfiles-picker` (portal termfilechooser, Firefox). Ver INSTALAR-SELETOR.md.
- Imagens/vídeo/áudio abrem com xdg-open em vez do JCode. Lógica pura em jfcore.py (+ tests/test_jfcore.py, test_jfiles_estado.py).
- Precisa de jstatus.py (do patch do JCode) na mesma pasta para as pílulas; sem ele cai num visual simples.
