# JDev

> Um ambiente de desenvolvimento pessoal feito do zero, para terminal.

O **JDev** é um conjunto de ferramentas que estou desenvolvendo para criar meu próprio ambiente de desenvolvimento no terminal.

A ideia é simples: cada ferramenta funciona de forma independente, mas juntas elas formam um ambiente completo para trabalhar com código e arquivos.

```text
JDev
├── JShell   → terminal
├── JCode    → editor de código
└── JFiles   → gerenciador de arquivos
```

## 🧩 Componentes

### JShell

Um shell próprio para executar comandos e servir como ponto de entrada do ambiente JDev.

```text
JShell
├── comandos do sistema
├── integração com JCode
└── integração com JFiles
```

### JCode

Um editor de código executado diretamente no terminal.

Construído com `prompt_toolkit`, possui interface própria, edição de arquivos, navegação pelo código e uma barra de status no rodapé.

### JFiles

Um gerenciador de arquivos para navegar pelos diretórios e trabalhar com os arquivos diretamente pelo terminal.

A ideia é que ele possa ser usado sozinho ou aberto através do JShell.

---

## 🔗 Feitos para trabalhar juntos

Um dos objetivos principais do JDev é fazer com que as ferramentas possam conversar entre si.

Por exemplo:

```text
              ┌─────────┐
              │ JShell  │
              └────┬────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
      ┌────────┐        ┌────────┐
      │ JCode  │        │ JFiles │
      └────────┘        └────────┘
```

Mas elas também podem funcionar individualmente.

A ideia é manter cada programa simples e independente, enquanto a integração transforma o conjunto em um ambiente maior.

---

## 🛠️ Tecnologias

O projeto é desenvolvido principalmente em **Python**.

Algumas das tecnologias utilizadas:

* Python
* `prompt_toolkit`
* `pyperclip`
* `pathlib`
* `ast`
* `subprocess`

---

## 🚧 Estado do projeto

O JDev ainda está em desenvolvimento.

Atualmente, o projeto já possui:

* [x] JShell
* [x] JCode
* [x] JFiles
* [x] Interface de terminal
* [x] Edição de arquivos
* [x] Navegação por arquivos
* [x] Integração entre ferramentas
* [ ] Mais comandos para o JShell
* [ ] Melhorias na integração entre os programas
* [ ] Mais recursos para o JCode
* [ ] Mais recursos para o JFiles
* [ ] Documentação completa

---

## 🚀 Executando

Clone o repositório:

```bash
git clone https://github.com/jacob-derek/JDev.git
cd JDev
```

Depois, execute a ferramenta desejada.

> Os comandos de execução podem mudar conforme o projeto evolui.

---

## 🗺️ Roadmap

Algumas coisas que pretendo explorar no futuro:

* Melhorar a integração entre JShell, JCode e JFiles
* Criar mais comandos próprios
* Melhorar a experiência de edição no JCode
* Expandir o gerenciamento de arquivos
* Criar configurações personalizáveis
* Melhorar a documentação
* Deixar o ambiente cada vez mais consistente

O roadmap não é fixo. O projeto está sendo construído conforme novas ideias aparecem.

---

## 💡 Sobre o projeto

O JDev começou como uma ideia de criar minhas próprias ferramentas para desenvolvimento no terminal.

Mais do que apenas fazer um editor ou um shell, a intenção é experimentar e entender como essas ferramentas funcionam por dentro, construindo tudo aos poucos.

É um projeto pessoal e ainda está em evolução.

**Cada parte do JDev existe porque eu quis construir.**

---

## 📌 Projeto

**JDev**
GitHub: https://github.com/jacob-derek/JDev

Feito por **Jacob Derek**.
