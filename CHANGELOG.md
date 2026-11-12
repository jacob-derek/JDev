# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e versionamento
semântico (`MAJOR.MINOR.PATCH`).

## [Não lançado]

### Adicionado
- **Fonte única** (`jtheme.py`): `JFONT=nome` ou `~/.config/jdev/font` escolhem a fonte de JTerm, JBar e JRun.
  Sem pedido, vale a primeira instalada entre JetBrains Mono, Iosevka, Commit Mono e DejaVu Sans Mono.
- **Tema Void**: preto de verdade (`python3 jtheme.py set void`).
- `jwm-session` ajusta o Xft (hinting leve, antialias) pelo `xrdb`; `JWM_XFT=0` desliga.

### Alterado
- JTerm: respiro interno de 12 px (`JTERM_PAD=8` volta ao antigo) e cabeçalho dos painéis em fonte monoespaçada.

## [1.0.0] - 2026-11-07

Primeira versão oficial: estável, bonita e leve.

### Adicionado
- **JWM**: mosaico em árvore estilo Sway (`jtile.py`), com divisões horizontais e verticais,
  troca de janelas de lugar por direção e redimensionamento pela divisória, incluindo o modo
  resize (`Super+R`).
- **JWM**: borda colorida na janela focada, atalhos `Super+B`/`Super+V`/`Super+T` para controlar
  a divisão e `--no-ui` (apelido de `--no-jdesk`) para subir só o gerenciador de janelas.
- **JBar**: barra em pílulas no rodapé, em faixa reservada, que o JWM publica em
  `~/.cache/jwm-state.json` (modo, divisão pendente, título); `Super+Shift+B` mostra e esconde.
- **Temas** (`jtheme.py`): Tokyo Night, Catppuccin Mocha, Gruvbox Dark, Dawn (claro) e Ashes. O tema vale para
  JWM, JBar, JDesk, JTerm, JCode, JFiles, JShell e JRun, e o `jtheme.py` é opcional: sem ele
  cada programa usa o Tokyo Night embutido.
- **Wallpaper por monitor** (`jwm-layout`): `horizontal.*` e `vertical.*` em `~/.config/jdev/`,
  escolhidos pela orientação real de cada monitor.
- Testes (`tests/`), CI no GitHub Actions e o script `scripts/xephyr-test.sh` para testar o JWM
  num X aninhado, sem arriscar a sessão.
