#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
bin_dir="$HOME/.local/bin"
data_dir="${XDG_DATA_HOME:-$HOME/.local/share}"
icon_name="io.github.farah.archupdatecenter"
extension_uuid="arch-update-center-indicator@eliasfarah.github.io"
extension_source="$project_dir/gnome-extension/$extension_uuid"
extension_dir="$data_dir/gnome-shell/extensions/$extension_uuid"

install -Dm755 "$project_dir/main.py" "$bin_dir/arch-update-center"
install -Dm644 "$project_dir/data/icons/hicolor/scalable/apps/$icon_name.svg" \
  "$data_dir/icons/hicolor/scalable/apps/$icon_name.svg"
install -Dm644 "$project_dir/arch-update-center.desktop" \
  "$data_dir/applications/arch-update-center.desktop"

python3 - "$data_dir/applications/arch-update-center.desktop" "$bin_dir/arch-update-center" <<'PY'
from pathlib import Path
import sys

desktop_path, executable = map(Path, sys.argv[1:])
text = desktop_path.read_text()
escaped = str(executable).replace("\\", "\\\\").replace('"', '\\"')
desktop_path.write_text(text.replace("Exec=arch-update-center", f'Exec="{escaped}"'))
PY

install -Dm644 "$extension_source/metadata.json" "$extension_dir/metadata.json"
install -Dm644 "$extension_source/extension.js" "$extension_dir/extension.js"

if command -v gnome-extensions >/dev/null 2>&1; then
  if gnome-extensions enable "$extension_uuid"; then
    printf 'Extensão GNOME ativada.\n'
  else
    python3 - "$extension_uuid" <<'PY'
from gi.repository import Gio
import sys

settings = Gio.Settings.new("org.gnome.shell")
enabled = settings.get_strv("enabled-extensions")
extension_uuid = sys.argv[1]
if extension_uuid not in enabled:
    settings.set_strv("enabled-extensions", enabled + [extension_uuid])
PY
    printf 'Extensão marcada para ativação; talvez seja necessário iniciar uma nova sessão do GNOME.\n'
  fi
else
  printf 'Extensão instalada; ative-a pelo app Extensões do GNOME.\n'
fi

printf 'Instalado. Procure “Central de atualizações do Arch” no menu de aplicativos.\n'
