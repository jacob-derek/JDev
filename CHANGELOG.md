# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e versionamento
semântico (`MAJOR.MINOR.PATCH`).

## [Não lançado]

### Corrigido
- jbash: se o bash não responde ao iniciar (ex.: erro no init ou no `~/.bashrc`), o JShell desiste em 10 s e mostra o erro, em vez de travar em "JShell". O `init.bash` é gravado de forma atômica.
- jipc: entrega a um receptor travado tem limite de 1 s e a fila de pedidos do JDesk tem teto (256).
- jtile: orientação inválida vira horizontal.
- jterm_diag: mensagens claras sem DISPLAY/tkinter, em vez de traceback.
- start-jwm: escolhe o primeiro display livre (:0 a :9).

### Adicionado
- **JToast** (`JToast.py`): serviço de notificações (`org.freedesktop.Notifications`). Balões no canto superior direito do monitor principal, clique fecha, urgência por cor, limite contra enxurrada e texto sempre saneado. Precisa de `jeepney`; `--demo` testa só o visual.
- **Fonte única** (`jtheme.py`): `JFONT=nome` ou `~/.config/jdev/font` escolhem a fonte de JTerm, JBar e JRun.
  Sem pedido, vale a primeira instalada entre JetBrains Mono, Iosevka, Commit Mono e DejaVu Sans Mono.
- **Tema Void**: preto de verdade (`python3 jtheme.py set void`).
- `jwm-session` ajusta o Xft (hinting leve, antialias) pelo `xrdb`; `JWM_XFT=0` desliga.
- **JCode**: espaços no fim das linhas são removidos ao salvar (Ctrl+Z desfaz; `.md` fica de fora; a linha do cursor é poupada).
- **JCode**: quebra de linha visual (`F3` liga/desliga), com a continuação indentada e marcada com `›`.
- **JCode**: mapa do arquivo à direita (`F2`), em braille, com a janela visível, o cursor, `def`/`class` e erro de sintaxe destacados; clicar pula para o trecho.

### Alterado
- JCode: Tab no fim de uma linha que já tem código é ignorado (em linha vazia continua indentando).
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
