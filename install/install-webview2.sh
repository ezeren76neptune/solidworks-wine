#!/bin/bash
# Put Microsoft's WebView2 runtime into the prefix, registered the way the
# 3DEXPERIENCE sign-in page's loader looks for it. Without it SOLIDWORKS asks for
# WebView2, and you may get Wine's generic sign-in box: do not use that one.
#   install/install-webview2.sh <folder>|<Microsoft.WebView2.FixedVersionRuntime.*.x64.cab> [version]
# <folder> is a runtime version folder that contains msedgewebview2.exe, e.g. a copy of
# C:\Program Files (x86)\Microsoft\EdgeWebView\Application\157.0.4341.42 from a Windows PC.
# The .cab is the x64 "Fixed Version" runtime from Microsoft's WebView2 download page.
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
SW="$SW_ROOT/bin/sw-wine"
SRC="${1:?usage: install-webview2.sh <runtime folder or .cab> [version]}"
TMP=
if [ -f "$SRC" ]; then
    command -v cabextract >/dev/null || { echo "cabextract is required for a .cab" >&2; exit 1; }
    TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
    cabextract -q -d "$TMP" "$SRC"
    EXE=$(find "$TMP" -name msedgewebview2.exe | head -1)
    [ -n "$EXE" ] || { echo "no msedgewebview2.exe in $SRC" >&2; exit 1; }
    DIR=$(dirname "$EXE"); NAME=$(basename "$SRC")
else
    DIR="$SRC"; NAME=$(basename "$(readlink -f "$SRC")")
fi
[ -e "$DIR/msedgewebview2.exe" ] || { echo "no msedgewebview2.exe in $DIR" >&2; exit 1; }
VER="${2:-$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' <<< "$NAME" | head -1)}"
[ -n "$VER" ] || { echo "cannot tell the version from '$NAME'; pass it as the second argument" >&2; exit 1; }

APP='C:\Program Files (x86)\Microsoft\EdgeWebView\Application'
DEST="$WINEPREFIX/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application/$VER"
mkdir -p "$DEST"
cp -a "$DIR"/. "$DEST"/
GUID='{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
reg() { "$SW" wine reg add "$@" /f >/dev/null; }
K="HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate"
reg "$K\\Clients\\$GUID" /v pv /d "$VER"
reg "$K\\Clients\\$GUID" /v name /d 'Microsoft Edge WebView2 Runtime'
reg "$K\\Clients\\$GUID" /v location /d "$APP"
reg "$K\\ClientState\\$GUID" /v EBWebView /d "$APP\\$VER"
echo "WebView2 $VER installed in $DEST"
