#!/usr/bin/env python3

import curses
import random
import time

WORDS = """
python terminal teclado codigo arquivo funcao classe objeto
linux sistema janela editor trabalho rapido lento simples
mouse tela texto palavra digitar escrever teclado dedos
while for import return print input string lista tupla
commit branch merge push pull git github projeto pasta
shell comando processo memoria sistema usuario arquivo
def main loop break continue try except finally
jwrite jdev programar criar testar executar aprender
""".split()


def center(stdscr, y, text, color=0):
    height, width = stdscr.getmaxyx()
    if 0 <= y < height:
        x = max(0, (width - len(text)) // 2)
        stdscr.addstr(y, x, text[:max(0, width - x - 1)], color)


def game(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_WHITE, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_CYAN, -1)

    green = curses.color_pair(1)
    white = curses.color_pair(2)
    red = curses.color_pair(3)
    cyan = curses.color_pair(4)

    while True:
        stdscr.erase()
        center(stdscr, 3, "J W R I T E", green | curses.A_BOLD)
        center(stdscr, 5, "FINGER WARM-UP", white)
        center(stdscr, 8, "30 segundos. Aqueça esses dedos.", cyan)
        center(stdscr, 10, "Digite cada palavra e pressione ENTER.", white)
        center(stdscr, 12, "BACKSPACE corrige | ESC sai", white)
        center(stdscr, 15, "[ ENTER ] COMEÇAR", green | curses.A_BOLD)
        stdscr.refresh()

        key = stdscr.getch()
        if key == 27:
            return
        if key in (10, 13, curses.KEY_ENTER, 32):
            break
        time.sleep(0.03)

    correct = 0
    errors = 0
    typed_chars = 0
    word = random.choice(WORDS)
    typed = ""
    start = time.monotonic()
    duration = 30

    while True:
        elapsed = time.monotonic() - start
        remaining = max(0, duration - elapsed)

        if remaining <= 0:
            break

        stdscr.erase()
        center(stdscr, 2, "JWRITE / QUICK TYPING", green | curses.A_BOLD)
        center(stdscr, 4, f"TEMPO  {remaining:04.1f}s", cyan)
        center(stdscr, 7, word, white | curses.A_BOLD)

        height, width = stdscr.getmaxyx()
        prompt = "> " + typed
        center(stdscr, 9, prompt, green)

        center(stdscr, 12, f"ACERTOS {correct}   ERROS {errors}", white)
        center(stdscr, 14, "ESC para encerrar", white)
        stdscr.refresh()

        key = stdscr.getch()

        if key == -1:
            time.sleep(0.01)
            continue

        if key == 27:
            break

        if key in (curses.KEY_BACKSPACE, 127, 8):
            typed = typed[:-1]

        elif key in (10, 13, curses.KEY_ENTER):
            typed_chars += len(typed)

            if typed == word:
                correct += 1
            else:
                errors += 1

            typed = ""
            word = random.choice(WORDS)

        elif 32 <= key <= 126 and len(typed) < 40:
            typed += chr(key)

    elapsed = max(0.1, time.monotonic() - start)
    wpm = correct * 60 / elapsed
    accuracy = 100 * correct / max(1, correct + errors)

    stdscr.nodelay(False)
    stdscr.erase()
    center(stdscr, 3, "JWRITE / RESULTADO", green | curses.A_BOLD)
    center(stdscr, 6, f"Palavras corretas: {correct}", white)
    center(stdscr, 8, f"Palavras erradas:  {errors}", red)
    center(stdscr, 10, f"Velocidade:        {wpm:.1f} PPM", cyan)
    center(stdscr, 12, f"Precisão:          {accuracy:.1f}%", green)
    center(stdscr, 16, "R = jogar novamente | ESC = sair", white)
    stdscr.refresh()

    while True:
        key = stdscr.getch()
        if key in (ord("r"), ord("R")):
            return game(stdscr)
        if key == 27 or key in (ord("q"), ord("Q")):
            return


if __name__ == "__main__":
    try:
        curses.wrapper(game)
    except KeyboardInterrupt:
        pass