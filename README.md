# JDev

> Um ambiente de desenvolvimento em Python, feito para o terminal, reunindo editor, shell e navegador de arquivos.

O **JDev** é um projeto pessoal em desenvolvimento. A ideia é construir um ambiente leve, modular e integrado para programar e trabalhar com arquivos sem sair do terminal.

## Componentes

| Componente | Descrição |
|---|---|
| **JCode** | Editor de código em tela cheia, com destaque de sintaxe e ferramentas para Python. |
| **JShell** | Shell interativo com comandos próprios e acesso aos utilitários do JDev. |
| **JFiles** | Navegador de arquivos em TUI, com operações de gerenciamento e preview. |
| **JDevTodo** | Lista de tarefas em janela Tkinter flutuante para acompanhar o desenvolvimento. |

## Funcionalidades

### JCode — editor

- Interface de terminal em tela cheia, construída com `prompt_toolkit`.
- Edição de arquivos com salvamento por `Ctrl+S`.
- Indicador de estado do arquivo: salvo ou modificado.
- Números de linha e destaque da linha atual.
- Guias visuais de indentação.
- Realce de sintaxe por meio do Pygments, selecionado conforme a extensão/nome do arquivo.
- Validação sintática de Python em tempo real, com indicação de linha, coluna e mensagem do erro.
- Painel **Outline/Sumário** para arquivos Python, identificando funções, funções assíncronas e classes por meio da AST.
- Navegação pelo sumário para saltar até uma definição.
- Indentação com `Tab`.
- Selecionar tudo, copiar, recortar e colar por atalhos implementados no editor.
- Interface com tema escuro inspirado no Gruvbox.
- Suporte a mouse.

### JShell — shell

- Prompt interativo com o diretório atual visível.
- Autocomplete de comandos conhecidos.
- Comandos próprios para navegação e gerenciamento de arquivos.
- Integração para abrir o JCode e o JFiles.
- Saída colorida e mensagens de erro/sucesso.
- Expansão de `~` e suporte a caminhos relativos nos comandos de arquivo.

#### Comandos disponíveis

| Comando | Função |
|---|---|
| `help` | Exibe a ajuda de comandos. |
| `exit` | Encerra o JShell. |
| `clear` | Limpa a tela. |
| `pwd` | Mostra o diretório atual. |
| `ls` | Lista pastas e arquivos, com tamanhos. |
| `cd <pasta>` | Muda o diretório atual. |
| `mkdir <pasta>` | Cria uma pasta. |
| `rd <pasta>` | Remove uma pasta vazia. |
| `touch <arquivo>` | Cria um arquivo vazio. |
| `ren <origem> <destino>` | Renomeia um arquivo ou pasta. |
| `cp <origem> <destino>` | Copia arquivo ou pasta. |
| `mv <origem> <destino>` | Move arquivo ou pasta. |
| `rm <arquivo>` | Remove um arquivo. |
| `cat <arquivo>` | Exibe o conteúdo de um arquivo. |
| `open <arquivo>` | Abre um arquivo com o programa padrão do sistema. |
| `jcode <arquivo>` | Abre um arquivo no JCode. |
| `jcode new <arquivo>` | Abre um arquivo novo no JCode para criação. |
| `jfiles` | Abre o navegador JFiles. |

> Observação: o JShell é um shell com comandos próprios; não é um substituto completo do Bash. Para executar comandos arbitrários do sistema, use o terminal do sistema.

### JFiles — navegador de arquivos

- Interface TUI com navegação por teclado.
- Pastas listadas antes dos arquivos, em ordem alfabética.
- Ícones e tamanhos dos arquivos.
- Preview do conteúdo de arquivos de texto e da lista de conteúdo de pastas.
- Visualização de informações: caminho, tipo, extensão, tamanho, data de modificação e quantidade de itens em pastas.
- Criar arquivos e pastas.
- Renomear, copiar, mover e excluir itens.
- Confirmação de exclusão.
- Abertura de arquivos selecionados no JCode.
- Mensagens de status e tratamento de erros de acesso/permissão.
- Layout adaptável ao tamanho do terminal e suporte a mouse.

### JDevTodo — lista de tarefas

- Janela desktop feita com Tkinter.
- Mantém-se acima das outras janelas.
- Tarefas separadas por áreas do projeto.
- Checkboxes e contador de tarefas concluídas.
- Área rolável e botão para limpar as marcações.
- Tema escuro alinhado à identidade visual do JDev.

## Instalação

### Requisitos

- Python 3.10 ou superior (versão recomendada; o projeto pode funcionar em versões próximas compatíveis).
- Terminal com suporte a sequências de controle ANSI.
- Para a interface de tarefas: Tkinter.
- Bibliotecas Python usadas pelo projeto:

```bash
pip install prompt_toolkit pygments pyperclip
```

Em algumas distribuições Linux, o Tkinter precisa ser instalado pelo gerenciador de pacotes do sistema. No Debian, por exemplo:

```bash
sudo apt install python3-tk
```

## Como executar

Clone o repositório:

```bash
git clone https://github.com/jacob-derek/JDev.git
cd JDev
```

Inicie o shell:

```bash
python3 JShell.py
```

Abra o navegador de arquivos diretamente:

```bash
python3 JFiles.py
```

Abra a lista de tarefas:

```bash
python3 JDevTodo.py
```

O JCode normalmente é iniciado pelo JShell ou pelo JFiles:

```bash
python3 JCode.py caminho/para/arquivo.py
```

## Estrutura do projeto

```text
JDev/
├── JCode.py       # Editor de código
├── JShell.py      # Shell interativo
├── JFiles.py      # Navegador e gerenciador de arquivos
├── JDevTodo.py    # Lista de tarefas desktop
└── README.md
```

## Tecnologias

- Python
- `prompt_toolkit` — interface interativa de terminal
- Pygments — realce de sintaxe
- Python AST — análise estrutural de código Python
- `pyperclip` — integração com a área de transferência
- Tkinter / ttk — janela da lista de tarefas

## Em desenvolvimento

Algumas ideias registradas para versões futuras:

- Abas no JCode e terminais secundários.
- Busca no editor e navegação direta para uma linha.
- Melhorias no Outline e autocomplete de símbolos.
- Execução de código diretamente pelo JCode.
- Autocomplete de caminhos no JShell.
- Histórico de comandos e informações do sistema.
- Busca no JFiles e escolha entre abrir ou executar arquivos.
- Integração mais profunda entre os componentes e configuração/tema compartilhados.

## Estado do projeto

O JDev está em desenvolvimento ativo. Recursos, atalhos e compatibilidade podem mudar entre versões.
