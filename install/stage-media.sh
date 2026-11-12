#!/bin/bash
# Unpack the SOLIDWORKS installer media ("bootstrap") into C:\DSInstall and
# patch its installer stubs so they run under Wine.
#   install/stage-media.sh SOLIDWORKS_3DEXP_Desktop.Full-CP0490V6R2026x.HF5.9.Windows64.zip
# (or a folder that already contains SOLIDWORKS_3DEXP_Desktop.Full.Windows64/1 ... /8)
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
SRC="${1:?usage: stage-media.sh <bootstrap .zip or folder>}"
DEST="$WINEPREFIX/drive_c/DSInstall"
mkdir -p "$DEST"
if [ -f "$SRC" ]; then
    unzip -q -o "$SRC" -d "$DEST"
else
    cp -a --reflink=auto "$SRC"/. "$DEST"/
fi
V1=$(ls -d "$DEST"/*.Windows64/1 2>/dev/null | head -1)
[ -n "$V1" ] && [ -e "$V1/setup.exe" ] || { echo "no <name>.Windows64/1/setup.exe under $DEST" >&2; exit 1; }
# The stubs refuse to start without "Internet Explorer 10" (a wininet export
# Wine lacks); flip that one check.
python3 -I "$SW_ROOT/install/patch-ie10-check.py" "$V1"/setup.exe "$V1"/StartTUI.exe "$V1"/setup_noUAC.exe
echo "media staged: $V1"
