#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
template="$project_dir/systemd/spotifierd.service.in"
unit_dir="$HOME/.config/systemd/user"
unit="$unit_dir/spotifierd.service"

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
