#!/bin/bash
# Pre-download the installer's component archives (CAFs) from Dassault's public
# download bucket into the folder the installer reads them from.
#   install/download-cafs.sh [list.tsv]     (default: cafs-R2026x-HF5.9.tsv, ~7 GB)
# The list is for media CP0490V6R2026x.HF5.9 (R428, package T6PP9). For other
# media, make the same list from a Windows install's
# C:\ProgramData\DassaultSystemes\3DEXPERIENCELauncher\defaultDataStore\Cafs folder.
# Re-run to resume; files already complete are skipped.
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
TSV="${1:-$SW_ROOT/install/cafs-R2026x-HF5.9.tsv}"
DEST="$WINEPREFIX/drive_c/ProgramData/DassaultSystemes/3DEXPERIENCELauncher/defaultDataStore/Cafs/R428/428.6.9/FULL/CODE/win_b64"
mkdir -p "$DEST"
export DEST
dl() {
    local name=$1 size=$2 url=$3 out="$DEST/$1.dsa"
    [ -f "$out" ] && [ "$(stat -c %s "$out")" = "$size" ] && return 0
    curl -sS -f -L --retry 5 --retry-delay 3 -C - -o "$out" "$url" || { echo "FAILED $name" >&2; return 1; }
    [ "$(stat -c %s "$out")" = "$size" ] || { echo "WRONG SIZE $name" >&2; return 1; }
}
export -f dl
# largest first, 8 at a time
tail -n +2 "$TSV" | sort -t$'\t' -k2,2nr | cut -f1,2,4 |
    xargs -P 8 -d '\n' -n 1 bash -c 'IFS=$'"'"'\t'"'"' read -r n s u <<< "$0"; dl "$n" "$s" "$u"'
echo "$(ls "$DEST" | wc -l) archives in $DEST"
