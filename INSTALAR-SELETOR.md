# JFiles como seletor de arquivos do Firefox

1. Instalar o portal que chama um gerenciador de terminal:
   `xdg-desktop-portal-termfilechooser` (github.com/boydaihungst/xdg-desktop-portal-termfilechooser).
   No Void não achei pacote: compila-se com meson/ninja (`xbps-install meson ninja inih scdoc elogind-devel xdg-desktop-portal`), conforme o README do projeto.
2. `~/.config/xdg-desktop-portal-termfilechooser/config`:
   ```
   [filechooser]
   cmd=/home/jacob/JDev/jfiles-picker
   default_dir=$HOME
   ```
3. `~/.config/xdg-desktop-portal/portals.conf`:
   ```
   [preferred]
   default=gtk
   org.freedesktop.impl.portal.FileChooser=termfilechooser
   ```
   (precisa de xdg-desktop-portal >= 1.18; reinicie o portal: `pkill xdg-desktop-portal`).
4. Firefox → `about:config` → `widget.use-xdg-desktop-portal.file-picker` = `1`.
5. Teste sem Firefox: `jfiles-picker 0 0 0 ~ /tmp/saida && cat /tmp/saida`.

Arrastar para fora (tecla `d`): instale `ripdrag` (cargo install ripdrag) ou `dragon-drop`.
