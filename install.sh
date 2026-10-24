#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
bin_dir="$HOME/.local/bin"
data_dir="${XDG_DATA_HOME:-$HOME/.local/share}"
icon_name="io.github.farah.archupdatecenter"

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

printf 'Instalado. Procure “Central de atualizações do Arch” no menu de aplicativos.\n'
