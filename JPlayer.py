#!/usr/bin/env python3
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

try:
    import pygame
except ImportError:
    pygame = None

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

BG = "#101010"
PANEL = "#161616"
FG = "#d0d0d0"
DIM = "#777777"
BORDER = "#303030"
SUPPORTED = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}


class JPlayer:
    def __init__(self, root):
        self.root = root
        self.root.title("JPlayer")
        self.root.geometry("760x600")
        self.root.minsize(620, 500)
        self.root.configure(bg=BG)

        self.folder = None
        self.queue = []
        self.index = -1
        self.playing = False
        self.paused = False
        self.duration = 0
        self.cover_photo = None

        if pygame:
            pygame.mixer.init()

        self.build_ui()
        self.root.bind("<space>", lambda e: self.toggle_play())
        self.root.bind("<Left>", lambda e: self.previous())
        self.root.bind("<Right>", lambda e: self.next())
        self.root.bind("<Return>", lambda e: self.play_selected())
        self.update_loop()

    def build_ui(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=18, pady=(14, 8))
        tk.Label(header, text="JPLAYER", bg=BG, fg=FG,
                 font=("TkFixedFont", 16, "bold")).pack(side="left")

        self.folder_label = tk.Label(header, text="no folder", bg=BG, fg=DIM,
                                     font=("TkFixedFont", 9))
        self.folder_label.pack(side="right")
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", padx=18)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=14)

        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="y")

        self.cover = tk.Label(left, text="[ NO COVER ]", bg=PANEL, fg=DIM,
                              width=28, height=14, font=("TkFixedFont", 11))
        self.cover.pack()

        self.title_label = tk.Label(left, text="Nothing playing", bg=BG, fg=FG,
                                    font=("TkFixedFont", 12, "bold"), anchor="w")
        self.title_label.pack(fill="x", pady=(12, 2))
        self.artist_label = tk.Label(left, text="", bg=BG, fg=DIM,
                                     font=("TkFixedFont", 9), anchor="w")
        self.artist_label.pack(fill="x")

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(22, 0))

        tk.Label(right, text="QUEUE", bg=BG, fg=DIM,
                 font=("TkFixedFont", 9, "bold"), anchor="w").pack(fill="x")

        frame = tk.Frame(right, bg=PANEL, highlightbackground=BORDER,
                         highlightthickness=1)
        frame.pack(fill="both", expand=True, pady=(6, 0))

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        self.queue_list = tk.Listbox(
            frame, bg=PANEL, fg=FG, selectbackground="#333333",
            selectforeground=FG, activestyle="none", relief="flat",
            borderwidth=0, font=("TkFixedFont", 10),
            yscrollcommand=scrollbar.set)
        self.queue_list.pack(fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self.queue_list.yview)
        self.queue_list.bind("<Double-Button-1>", self.play_selected)

        controls = tk.Frame(self.root, bg=BG)
        controls.pack(fill="x", padx=18, pady=(0, 8))

        self.time_label = tk.Label(controls, text="0:00", bg=BG, fg=DIM,
                                   font=("TkFixedFont", 9))
        self.time_label.pack(side="left")

        self.progress = tk.Scale(
            controls, from_=0, to=1000, orient="horizontal", showvalue=False,
            resolution=1, command=self.seek, bg=BG, fg=FG,
            troughcolor=BORDER, highlightthickness=0, bd=0)
        self.progress.pack(side="left", fill="x", expand=True, padx=10)

        self.duration_label = tk.Label(controls, text="0:00", bg=BG, fg=DIM,
                                       font=("TkFixedFont", 9))
        self.duration_label.pack(side="right")

        buttons = tk.Frame(self.root, bg=BG)
        buttons.pack(pady=(0, 14))
        self.make_button(buttons, "⏮", self.previous, 0)
        self.make_button(buttons, "▶", self.toggle_play, 1)
        self.make_button(buttons, "⏭", self.next, 2)
        self.make_button(buttons, "FOLDER", self.choose_folder, 3)

        self.status = tk.Label(self.root, text="ready", bg=PANEL, fg=DIM,
                               font=("TkFixedFont", 8), anchor="w",
                               padx=10, pady=5)
        self.status.pack(fill="x", side="bottom")

    def make_button(self, parent, text, command, column):
        btn = tk.Button(parent, text=text, command=command, bg=PANEL, fg=FG,
                        activebackground="#252525", activeforeground=FG,
                        relief="flat", bd=0, highlightbackground=BORDER,
                        highlightthickness=1, font=("TkFixedFont", 10, "bold"),
                        padx=18, pady=7)
        btn.grid(row=0, column=column, padx=4)
        if text == "▶":
            self.play_button = btn

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Escolher pasta de músicas")
        if not folder:
            return
        self.folder = Path(folder)
        self.folder_label.config(text=str(self.folder))
        self.queue = sorted(
            [p for p in self.folder.iterdir()
             if p.is_file() and p.suffix.lower() in SUPPORTED],
            key=lambda p: p.name.lower())
        self.index = -1
        self.refresh_queue()
        self.status.config(
            text=f"{len(self.queue)} faixa(s) encontrada(s)"
            if self.queue else "nenhuma música encontrada")

    def refresh_queue(self):
        self.queue_list.delete(0, "end")
        for i, path in enumerate(self.queue):
            self.queue_list.insert("end", ("> " if i == self.index else "  ") + path.stem)
        if self.index >= 0:
            self.queue_list.selection_clear(0, "end")
            self.queue_list.selection_set(self.index)
            self.queue_list.see(self.index)

    def play_selected(self, event=None):
        selection = self.queue_list.curselection()
        if selection:
            self.play_index(selection[0])
        elif self.index >= 0:
            self.play_index(self.index)

    def play_index(self, index):
        if not pygame:
            messagebox.showerror("JPlayer",
                                 "pygame não está instalado.\n\npip install pygame")
            return
        if not 0 <= index < len(self.queue):
            return
        path = self.queue[index]
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
        except Exception as exc:
            self.status.config(text=f"erro: {exc}")
            return

        self.index = index
        self.playing = True
        self.paused = False
        self.duration = self.read_duration(path)
        self.progress.set(0)
        self.duration_label.config(text=self.format_time(self.duration))
        self.update_metadata(path)
        self.refresh_queue()
        self.status.config(text=f"playing: {path.name}")

    def toggle_play(self):
        if not pygame:
            if self.queue:
                self.play_index(self.index if self.index >= 0 else 0)
            return
        if not self.queue:
            return
        if self.index < 0:
            self.play_index(0)
        elif self.paused:
            pygame.mixer.music.unpause()
            self.paused = False
            self.playing = True
        elif self.playing:
            pygame.mixer.music.pause()
            self.paused = True
        else:
            self.play_index(self.index)

    def next(self):
        if self.queue:
            self.play_index((self.index + 1) % len(self.queue))

    def previous(self):
        if not self.queue:
            return
        if pygame and self.playing:
            try:
                if pygame.mixer.music.get_pos() > 3000:
                    pygame.mixer.music.play()
                    self.progress.set(0)
                    return
            except Exception:
                pass
        self.play_index((self.index - 1) % len(self.queue))

    def seek(self, value):
        if not pygame or not self.playing or self.duration <= 0:
            return
        try:
            pygame.mixer.music.set_pos(float(value) / 1000 * self.duration)
        except Exception:
            pass

    def read_duration(self, path):
        if MutagenFile:
            try:
                audio = MutagenFile(path)
                if audio and audio.info:
                    return max(0, int(audio.info.length))
            except Exception:
                pass
        return 0

    def update_metadata(self, path):
        title = path.stem
        artist = ""
        if MutagenFile:
            try:
                audio = MutagenFile(path, easy=True)
                if audio:
                    title = self.tag_value(audio, "title") or title
                    artist = self.tag_value(audio, "artist") or ""
            except Exception:
                pass
        self.title_label.config(text=title)
        self.artist_label.config(text=artist)
        self.load_cover(path)

    @staticmethod
    def tag_value(audio, key):
        value = audio.get(key)
        return value[0] if isinstance(value, list) and value else (value or "")

    def load_cover(self, path):
        self.cover_photo = None
        if not Image:
            self.cover.config(image="", text="[ NO COVER ]")
            return

        for candidate in (
            path.parent / "cover.jpg", path.parent / "cover.png",
            path.parent / "folder.jpg", path.parent / "folder.png"):
            if candidate.exists():
                try:
                    image = Image.open(candidate).convert("RGB")
                    image.thumbnail((280, 280))
                    self.cover_photo = ImageTk.PhotoImage(image)
                    self.cover.config(image=self.cover_photo, text="")
                    return
                except Exception:
                    pass
        self.cover.config(image="", text="[ NO COVER ]")

    def update_loop(self):
        if pygame and self.playing and not self.paused and self.index >= 0:
            try:
                pos = pygame.mixer.music.get_pos()
                if pos >= 0:
                    seconds = pos / 1000
                    self.time_label.config(text=self.format_time(seconds))
                    if self.duration:
                        self.progress.set(min(1000, seconds / self.duration * 1000))
                if not pygame.mixer.music.get_busy():
                    self.next()
            except Exception:
                pass
        self.root.after(250, self.update_loop)

    @staticmethod
    def format_time(seconds):
        seconds = max(0, int(seconds))
        return f"{seconds // 60}:{seconds % 60:02d}"


def main():
    root = tk.Tk()
    app = JPlayer(root)
    if not pygame:
        app.status.config(text="pygame não instalado — pip install pygame")
    root.mainloop()


if __name__ == "__main__":
    main()
