#!/bin/bash
# Point the launchers Wine created for this prefix (desktop icons, app-menu
# entries, and the .sldprt/.sldasm/.slddrw file associations) at bin/sw-wine.
# Started with plain `wine`, SOLIDWORKS gets none of the fixes and fails.
#   install/fix-desktop-entries.sh
# Re-run after Wine re-creates them (e.g. after a reinstall). Safe to re-run.
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
WRAP="$SW_ROOT/bin/sw-wine"
DESKTOP=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
DIRS=${SW_DESKTOP_DIRS:-"$DESKTOP:$HOME/.local/share/applications"}
python3 -I - "$WINEPREFIX" "$WRAP" "$DIRS" <<'EOF'
import os, sys
prefix, wrap, dirs = sys.argv[1], sys.argv[2], sys.argv[3].split(':')
old = 'WINEPREFIX=%s" wine ' % prefix
new = 'WINEPREFIX=%s" %s wine ' % (prefix, wrap)
n = 0
for d in dirs:
    for root, _, files in os.walk(d):
        for f in files:
            if not f.endswith('.desktop'):
                continue
            p = os.path.join(root, f)
            try:
                s = open(p, encoding='utf-8').read()
            except (OSError, UnicodeDecodeError):
                continue
            if old in s:
                open(p, 'w', encoding='utf-8').write(s.replace(old, new))
                print('fixed', p); n += 1
print(n, 'launcher(s) now use', wrap)
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
