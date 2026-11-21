## Tema do wallpaper + movimento
- `JTHEME=wallpaper` (ou `echo wallpaper > ~/.config/jdev/theme`): jwall.py acha a cor de destaque do wallpaper e deriva fundos, foco, bordas e a cor das janelas flutuantes dela. As cores de sintaxe/ANSI ficam as do tema base (`JTHEME_BASE`, padrão void). Cache em ~/.cache/jdev/wallpaper-theme.json; sem imagem/Pillow cai no tema padrão. Teste: `python3 jwall.py [imagem]`.
- jtheme: papel opcional `float` (cor da borda flutuante; antes sempre amarelo) e `misturar()`.
- JWM: fade da cor da borda ao mudar o foco (140 ms, ease-out; JWM_ANIM=0 desliga, JWM_ANIM_MS ajusta).
- JBar: o `♪` do player virou um mini equalizador animado enquanto toca.
- PICOM-ANIMACOES.md: fade (qualquer versão) ou animações do picom 12 (abrir/fechar/geometria).
