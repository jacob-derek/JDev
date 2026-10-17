# JWM — Window Manager experimental do JDev

**JWM é um gerenciador de janelas X11 independente. Não é um compositor Wayland e não roda dentro do Sway.** Para usá-lo, inicie uma sessão Xorg própria. O pacote não desinstala nem altera o Sway atual.

## O que ele faz

- Inicia o `JDesk.py` e o mantém como janela de desktop, sem borda e atrás das outras janelas.
- Mantém a barra superior do JDesk visível; os aplicativos normais ocupam o espaço abaixo dela.
- Organiza janelas externas em layout master/stack independente por monitor, permite flutuantes, fullscreen, foco pelo teclado, redimensionamento e quatro workspaces. O JDesk continua cobrindo os dois monitores como fundo.
- Usa `Super` (tecla Windows) nos atalhos do WM e deixa `Alt` livre para os atalhos que o JDesk/JTerm já usam.
- Não usa compositor, animações nem sombras. As janelas têm bordas simples para manter o WM pequeno.
- `Super+D` abre um executor de comandos (`JRun.py`), sem depender de dmenu/rofi.

É uma primeira versão funcional, não um clone completo do Sway. Ainda não tem decoração com barra de título nem regras avançadas de janelas.

## Instalação no Void Linux

É necessário ter Xorg/Xinit e `python-xlib`. No Void, os nomes de pacotes usados são `xorg`, `xinit` e `python3-xlib`:

```sh
sudo xbps-install -S xorg xinit python3-xlib
```

O JDesk também precisa das dependências já usadas pelo seu JDev, principalmente `pyte` e `prompt_toolkit`. `psutil`, Pillow e Pygments servem às funções existentes do JDev; alguns são opcionais conforme cada aplicativo.

Extraia o ZIP em qualquer lugar e instale no diretório existente do JDev:

```sh
sh ./install-jwm.sh "$HOME/JDev"
```

Se o JDev estiver noutro local, passe esse caminho como argumento. O instalador só copia `JWM.py`, `JRun.py`, `jwm-session` e `start-jwm`. Se arquivos com esses nomes já existirem, eles são copiados para `JDev/backups/JWM-before-DATA-HORA/` antes de serem substituídos. **Os arquivos originais do JDesk, JTerm, JShell, JCode, JFiles e JBar não são modificados.**

## Como iniciar

1. Primeiro salve seu trabalho.
2. Encerre a sessão gráfica atual e vá a um TTY (por exemplo, `Ctrl+Alt+F3`) e entre com seu usuário. Não execute o WM dentro da sessão Sway nem por cima de outro window manager.
3. Execute:

   ```sh
   cd "$HOME/JDev"
   ./start-jwm
   ```

O script tenta usar `:1` quando `:0` já existe e `:0` caso contrário. Se houver erro ao iniciar o servidor gráfico, volte ao TTY e consulte a saída do `startx`. Os logs do JWM ficam em `~/.cache/jwm.log`.

Para testar somente o WM, sem abrir o JDesk automaticamente:

```sh
python3 "$HOME/JDev/JWM.py" --no-jdesk
```

Esse comando também exige um servidor X11 vazio, sem outro WM controlando o display. Não o execute numa janela de terminal dentro do Sway/Cinnamon esperando substituir o gerenciador atual.

## Atalhos

| Atalho | Ação |
|---|---|
| `Super+Enter` | Abre o JTerm (JShell) |
| `Super+D` | Abre o JRun para digitar um comando/aplicativo |
| `Super+←/→/↑/↓` ou `Super+H/J/K/L` | Muda o foco entre janelas |
| `Super+Ctrl+←/→` | Diminui/aumenta a área master |
| `Super+Ctrl+↑/↓` | Ajusta a divisão vertical da pilha quando aplicável |
| `Super+Shift+←/→/↑/↓` | Reordena janelas tiled; em flutuantes, redimensiona |
| `Super+Shift+H/J/K/L` | Reordena janelas tiled; em flutuantes, redimensiona |
| `Super+Space` | Alterna tiled/flutuante |
| `Super+←/→/↑/↓` em janela flutuante | Move a janela |
| `Super+botão esquerdo do mouse` + arrastar | Torna flutuante e move |
| `Super+botão direito do mouse` + arrastar | Torna flutuante e redimensiona |
| `Super+F` | Alterna fullscreen |
| `Super+Tab` | Próxima janela |
| `Super+1…4` | Troca o workspace do WM |
| `Super+Shift+1…4` | Move a janela ativa para um workspace |
| `Super+Q` | Solicita o fechamento da janela ativa |
| `Super+Shift+Q` | Encerra o JWM e a sessão X iniciada pelo script |
| `Alt+1…4` | Continua reservado aos workspaces internos do JDesk |

## Recuperação

- `Super+Shift+Q` é a saída normal.
- Se a sessão ficar preta ou travada, tente voltar ao TTY de onde foi iniciada (`Ctrl+Alt+F3`) e interromper o `startx` ali.
- Para voltar ao Sway, encerre a sessão JWM e inicie seu Sway normalmente. JWM não altera a configuração do Sway.

## Teste realizado

O gerenciador passou em teste de sintaxe Python e num smoke test X11 com Xvfb: reconheceu uma janela JDesk simulada como desktop, pôs duas janelas por cima, reservou a faixa da barra e respondeu ao atalho de redimensionar a área master. Isso não substitui um teste no seu hardware, com seus drivers e todas as dependências reais do JDev.
