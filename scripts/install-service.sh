#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
template="$project_dir/systemd/spotifierd.service.in"
unit_dir="$HOME/.config/systemd/user"
unit="$unit_dir/spotifierd.service"

python -c 'import dbus; from gi.repository import GLib' || {
  printf 'Install python-dbus and python-gobject for desktop media controls\n' >&2
  exit 1
}

command -v cargo >/dev/null || {
  printf 'cargo is required to build the local Spotifier player\n' >&2
  exit 1
}
cargo build --release --manifest-path "$project_dir/player/Cargo.toml"

mkdir -p "$unit_dir"
python - "$template" "$unit" "$project_dir" <<'PY'
from pathlib import Path
import sys

template, destination, project = map(Path, sys.argv[1:])
content = template.read_text().replace("@PROJECT_DIR@", str(project))
destination.write_text(content)
PY

systemctl --user daemon-reload
systemctl --user enable --now spotifierd.service
printf 'Installed and started %s\n' "$unit"
