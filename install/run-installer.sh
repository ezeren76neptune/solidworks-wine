#!/bin/bash
# Run Dassault's SOLIDWORKS installer from C:\DSInstall with sw-install.json.
#   install/run-installer.sh
# Its window opens; click through its panels. Log: <repo>/logs/ds-setup-<time>.log,
# installer logs: C:\Program Files\Dassault Systemes\SOLIDWORKS 3DEXPERIENCE R2026x\InstallData\log
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
D="$WINEPREFIX/drive_c/DSInstall"
V1=$(ls -d "$D"/*.Windows64/1 2>/dev/null | head -1)
[ -n "$V1" ] || { echo "run install/stage-media.sh first" >&2; exit 1; }
[ -e "$D/sw-install.json" ] || { echo "run install/make-install-json.py first" >&2; exit 1; }
mkdir -p "$SW_ROOT/logs"
LOG="$SW_ROOT/logs/ds-setup-$(date +%Y%m%d-%H%M%S).log"
cd "$V1"
WINEDEBUG=fixme-all "$SW_ROOT/bin/sw-wine" wine setup.exe --multi 'C:\DSInstall\sw-install.json' \
    --xmlreport 'C:\DSInstall\report.xml' -wait > "$LOG" 2>&1 || true
echo "installer exited; Wine log: $LOG"
L=$(ls -dt "$WINEPREFIX/drive_c/Program Files/Dassault Systemes/SOLIDWORKS 3DEXPERIENCE R2026x/InstallData/log/"*/ 2>/dev/null | head -1)
[ -n "$L" ] && { echo "installer log: $L/Everything.log"; grep -nE 'failed|Error' "$L/Everything.log" | tail -5 || true; }
