#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plugin_src="$repo_dir/quickshell/omarchy-plugin"
plugin_dst="$HOME/.config/omarchy/plugins/yel728.spotifier"
shell_json="$HOME/.config/omarchy/shell.json"

mkdir -p "$HOME/.config/omarchy/plugins"
rm -rf "$plugin_dst"
ln -s "$plugin_src" "$plugin_dst"

if [[ -f "$shell_json" ]]; then
  cp "$shell_json" "$shell_json.bak.spotifier.$(date +%s)"
  python - <<'PY'
import json
from pathlib import Path
p=Path.home()/'.config/omarchy/shell.json'
data=json.loads(p.read_text())
layout=data.setdefault('bar',{}).setdefault('layout',{})
for section in ('left','center','right'):
    items=layout.get(section,[])
    new=[]
    inserted=False
    for item in items:
        if isinstance(item, dict) and item.get('id') in ('yel728.media','omarchy.media'):
            if not inserted:
                new.append({'id':'yel728.spotifier'})
                inserted=True
        else:
            if not (isinstance(item, dict) and item.get('id')=='yel728.spotifier'):
                new.append(item)
    layout[section]=new
if not any(isinstance(item, dict) and item.get('id')=='yel728.spotifier' for sec in layout.values() for item in sec):
    left=layout.setdefault('left',[])
    idx=next((i+1 for i,item in enumerate(left) if isinstance(item, dict) and item.get('id')=='omarchy.workspaces'), len(left))
    left.insert(idx, {'id':'yel728.spotifier'})
disabled=data.setdefault('disabledPlugins',[])
for pid in ('omarchy.media','yel728.media'):
    if pid not in disabled:
        disabled.append(pid)
p.write_text(json.dumps(data, indent=2)+"\n")
PY
fi

"$repo_dir/scripts/install-service.sh"

if command -v omarchy >/dev/null; then
  omarchy restart shell >/dev/null 2>&1 || true
fi

echo "Installed yel728.spotifier Omarchy bar widget."
