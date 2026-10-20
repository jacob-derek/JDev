# JDev

> Um ambiente de desenvolvimento em Python feito para o terminal: editor, shell, explorador de arquivos, cliente do Google Classroom, emulador de terminal, um "desktop" de painéis e até um window manager X11, todos integrados.

O JDev é um projeto pessoal em desenvolvimento ativo. A ideia é ter um ambiente leve, modular e **integrado**, onde cada ferramenta funciona sozinha, mas fica melhor junto das outras.

```
┌ 1 2 3 4 ─────────────── qui 17 out  14:32 ──────── VOL 65%  RAM 42%  NET ↓1.2M ↑30K  CPU 12% ┐
│                                          JFILES                                              │
├──────────────────────┬───────────────────────────────────┬───────────────────────────────────┤
│ JSHELL               │ JCODE                             │ JCLASS                            │
└──────────────────────┴───────────────────────────────────┴───────────────────────────────────┘
```

## Componentes

| Componente | Descrição |
|---|---|
| **JCode** | Editor de código em tela cheia, com realce de sintaxe, validação de Python e sumário (outline). |
| **JShell** | Shell interativo com comandos próprios, autocomplete e integração com os outros programas. |
| **JFiles** | Navegador de arquivos em TUI, com preview, operações de gerenciamento e atualização automática. |
| **JClass** | Baixador de materiais do Google Classroom/Drive, organizado por turma. |
| **JTerm** | Emulador de terminal (Tkinter + `pyte` + PTY) que renderiza os outros programas. |
| **JDesk** | Janela única com 4 painéis (JFiles, JShell, JCode, JClass) e 4 workspaces, controlada pelo teclado. |
| **JSlides** | Visualizador de `.pptx`, `.ppt`, `.odp` e `.pdf`, embutido no JDesk (ou avulso). |
| **JBar** | Barra superior do JDesk: workspaces, hora, volume, RAM, rede e CPU. |
| **jipc** | Canal de mensagens que permite aos programas conversarem dentro do JDesk. |
| **JWM** | Window manager X11 minimalista (python-xlib) que usa o JDesk como desktop de fundo. |
| **JRun** | Executor de comandos simples para o JWM. |

## Como os programas se conversam

Dentro do JDesk, cada painel roda um programa num pty próprio, e o `jipc` os conecta:

- **Enter num arquivo no JFiles** abre o arquivo no painel do JCode (que fica em modo *idle* esperando).
- **`jcode arquivo` no JShell** também abre no painel do JCode (`jcode --aqui arquivo` abre no próprio terminal).
- **Um download concluído no JClass** faz o JFiles reler a pasta na hora.
- Ao fechar um arquivo no JCode (Ctrl+Q), o foco volta para o JFiles.

Fora do JDesk, tudo continua funcionando de forma independente, cada programa no seu terminal, como sempre.

O canal usa um servidor TCP em `127.0.0.1` (porta aleatória) com token por sessão; só os processos iniciados pelo JDesk recebem as credenciais, via variáveis de ambiente.

## Instalação

### Requisitos

- Linux (o JTerm também tem suporte a Windows via `pywinpty`, e o volume a macOS, mas o uso diário é em Linux).
- Python 3.10 ou superior.
- Tkinter (no Debian/Ubuntu: `sudo apt install python3-tk`).

### Dependências Python

```bash
# núcleo (JCode, JShell, JFiles)
pip install prompt_toolkit pygments pyperclip

# JTerm / JDesk / JBar
pip install pyte psutil pymupdf python-pptx

# JClass
pip install google-api-python-client google-auth-oauthlib

# opcionais
pip install pillow          # preview de imagens no JFiles
# LibreOffice (soffice): converte .pptx/.ppt/.odp para o JSlides
```

Para o **JWM** (window manager), é preciso também `python-xlib`, `startx` e Xorg/xinit. No Void Linux: `xbps-query -Rs python3-xlib`.

### Clonar

```bash
git clone https://github.com/jacob-derek/JDev.git
cd JDev
```

## Como executar

```bash
python3 JDesk.py      # o ambiente completo (painéis + workspaces + barra)
python3 JShell.py     # só o shell
python3 JFiles.py     # só o navegador de arquivos
python3 JCode.py caminho/do/arquivo.py
python3 JTerm.py      # um terminal com o JShell (ou: JTerm.py outro_comando)
```

### JDesk

A navegação segue o estilo do sway: o `$mod` é o **Alt** (o WM usa o Super), com `hjkl` ou setas. O resto das teclas vai direto ao programa do painel focado.

| Atalho | Ação |
|---|---|
| `Alt+h/j/k/l` ou `Alt+setas` | foco: esquerda / baixo / cima / direita |
| `Alt+Shift+h/j/k/l` ou `+setas` | **move** o painel (troca de lugar com o vizinho, sem reiniciar) |
| `Alt+1..4` | workspace 1 a 4 (ou clique na barra) |
| `Alt+f` (ou `Alt+z`) | tela cheia do painel / restaurar |
| `Alt+r` | **modo resize** (indicador na barra): `h`/`l` largura, `k`/`j` altura, `Enter`/`Esc` sai |
| `Alt+Shift+q` | encerra o programa do painel (`Enter` reinicia) |
| `Alt+Shift+r` | reinicia o painel |
| `Alt+Shift+e` | fecha o JDesk (com confirmação) |
| teclas de mídia | volume, mudo e brilho (`brightnessctl`) |
| `Alt+=` / `Alt+-` / `Alt+m` | volume +5% / −5% / mudo |

Cada workspace tem seus próprios 4 painéis e é criado só na primeira visita. Dentro de cada painel valem os atalhos do JTerm: `Ctrl+Shift+C/V` (copiar/colar), `Shift+PgUp/PgDn` e roda do mouse (histórico), `Ctrl+roda` (zoom da fonte daquele painel). Na barra, role o mouse sobre `VOL` para mudar o volume e clique para silenciar.

### JSlides

Abrir um `.pptx`, `.ppt`, `.odp` ou `.pdf` no JFiles (Enter), no JClass ou no JShell abre o visualizador num painel que cobre o workspace. `Esc` ou `q` fecha e devolve o foco. Também roda sozinho: `python3 JSlides.py arquivo.pptx`.

| Tecla | Ação |
|---|---|
| `→ ↓ PgDn espaço` / `← ↑ PgUp Backspace` | próximo / anterior (também `h j k l`) |
| `Home` / `End` | primeiro / último |
| `g` + número + `Enter` | ir para o slide |
| `o` | grade de miniaturas (setas, `Enter` escolhe) |
| `n` | notas do orador (pptx) |
| `f` | tela limpa |
| `r` | recarregar |

PDFs abrem direto (PyMuPDF). Os demais formatos são convertidos pelo LibreOffice em segundo plano e guardados em `~/.cache/jdesk/slides` (a segunda abertura é instantânea). Sem LibreOffice ou PyMuPDF, o `.pptx` abre em modo texto (python-pptx).

### JClass

Baixa os materiais e anexos dos avisos de uma turma do Google Classroom, separando por turma em `JClass/downloads/<turma>/`. Documentos nativos do Google são exportados (PDF, XLSX), e há política de conflito de nomes (renomear, ignorar ou substituir).

**Configuração (uma vez):**

1. No [Google Cloud Console](https://console.cloud.google.com/), crie um projeto e ative as APIs do **Classroom** e do **Drive**.
2. Crie uma credencial OAuth do tipo *aplicativo para computador* e salve o JSON como `JClass/credentials.json`.
3. Rode o JClass: na primeira vez ele abre o navegador para autorizar e cria o `token.json`.

Os escopos pedidos são somente leitura. **`credentials.json` e `token.json` nunca devem ser commitados** (o `.gitignore` já os ignora).

### JWM

Um window manager X11 minimalista: o JDesk vira o desktop de fundo (sem decoração), e as demais janelas usam layout master/stack, com modo flutuante opcional. O Alt fica reservado ao JDesk; os atalhos do WM usam **Super**:

| Atalho | Ação |
|---|---|
| `Super+Enter` | abre um terminal (JTerm) |
| `Super+D` | abre o JRun (executar comando) |
| `Super+Q` | fecha a janela ativa |
| `Super+F` | tela cheia |
| `Super+Espaço` | alterna flutuante |
| `Super+Shift+Q` | encerra o JWM |

Para iniciar: `./start-jwm` (de um TTY). Se já houver um X rodando, ele sobe um segundo servidor em `:1`. O log fica em `~/.cache/jwm.log`.

## JCode, JShell e JFiles

### JCode: editor

- Interface em tela cheia (`prompt_toolkit`), tema escuro inspirado no Gruvbox, suporte a mouse.
- Salvamento com `Ctrl+S`, indicador de arquivo salvo/modificado e aviso se o arquivo mudou no disco.
- Números de linha, guias de indentação, realce de sintaxe (Pygments) por extensão.
- Validação sintática de Python em tempo real, com linha, coluna e mensagem.
- Painel de sumário (outline) para Python, com salto até a definição.
- Seleção, copiar/recortar/colar e desfazer/refazer.
- **No JDesk:** modo *idle* — o painel espera arquivos enviados pelo JFiles/JShell/JClass e troca de arquivo sem fechar (se houver alterações não salvas, ele avisa e espera).

### JShell: shell

Prompt com diretório e ramo do git, autocomplete, histórico (`~/.jshell_history`), aliases e `~/.jshellrc`. Comandos próprios para arquivos e texto: `ls`, `cd`, `pwd`, `tree`, `mkdir`, `rd`, `touch`, `ren`, `cp`, `mv`, `rm`, `du`, `df`, `cat`, `head`, `tail`, `wc`, `grep`, `find`, `echo`, `which`, `env`, `export`, `alias`, `history`, `date`, `whoami`, `open`, `git`, além de `jcode`, `jfiles` e `help`. Programas externos funcionam, e linhas com pipes ou redirecionamentos são repassadas ao shell do sistema.

> O JShell não substitui o Bash: é um shell com comandos próprios.

### JFiles: navegador

Navegação por teclado, pastas antes dos arquivos, ícones, tamanhos, preview de texto (e de imagens, com Pillow) e de conteúdo de pastas, informações do item, criar/renomear/copiar/mover/excluir com confirmação, mensagens de erro de permissão e suporte a mouse. A lista **acompanha o disco sozinha** (um arquivo novo aparece sem precisar atualizar).

## Estrutura do projeto

```
JDev/
├── JCode.py  JShell.py  JFiles.py      # ferramentas principais
├── JTerm.py  JDesk.py  JBar.py         # terminal, desktop de painéis e barra
├── JSlides.py                          # visualizador de pptx/pdf
├── jipc.py                             # canal de mensagens entre programas
├── JWM.py  JRun.py                     # window manager e executor
├── start-jwm  jwm-session              # inicialização do JWM
├── JClass/                             # cliente do Google Classroom
│   ├── JClass.py  classroom_api.py  drive_download.py  testar_classroom.py
│   ├── credentials.json  token.json    # (locais, fora do git)
│   └── downloads/                      # (local, fora do git)
├── tools/                              # utilitários e experimentos
├── imagens/                            # ícones
└── docs/                               # anotações
```

> O núcleo fica **plano na raiz de propósito**: `JWM` procura `JDesk.py`, `JTerm.py` e `JRun.py` ao seu lado, e os módulos se importam entre si.

## Problemas conhecidos

- O JShell dentro do JTerm pode se comportar mal com linhas de comando muito longas (em investigação). Se acontecer, abra o JShell num terminal comum.

## Roadmap

- **`jdesk.toml`:** layout, atalhos e comandos dos painéis configuráveis.
- Mover painéis entre workspaces e layouts alternativos (como `splith`/`splitv`/`tabbed` do sway).
- Abas no JCode, busca no editor e no JFiles, execução de código pelo JCode.

## Versões

O desenvolvimento acontece na branch `dev`; a `main` guarda o que está estável, e cada marco recebe uma tag (`v0.x.y`). Para visitar uma versão antiga sem alterar nada:

```bash
git tag                              # lista as versões
git switch -c nostalgia v0.3.0       # cria uma branch a partir da tag
git switch main                      # volta quando quiser
```

## Tecnologias

Python · prompt_toolkit · Pygments · pyte · Tkinter · psutil · python-xlib · Google Classroom/Drive APIs · AST do Python

## Estado do projeto

Em desenvolvimento ativo. Recursos, atalhos e compatibilidade podem mudar entre versões.
