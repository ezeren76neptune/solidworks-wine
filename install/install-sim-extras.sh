#!/bin/bash
# Install eDrawings and SOLIDWORKS File Utilities from SOLIDWORKS Installation Manager media with
# msiexec, with the Installation Manager's own properties (docs/INSTALL-STANDALONE.md).
#   install/install-sim-extras.sh "<media folder>"
# Each runs from a patched copy (<name>-wine.msi next to the original, so its cabinets resolve) in
# which every deferred custom action continues on error: their regsvr32 shell-extension
# registrations can fail under Wine, and one failure would roll the whole package back.
# eDrawings also needs install/wpf-fixes.sh. Logs: C:\swtools\<name>-msi.log
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
SW="$SW_ROOT/bin/sw-wine"
MEDIA="$(readlink -f "${1:?usage: install-sim-extras.sh <Installation Manager media folder>}")"
WMEDIA=$("$SW" wine winepath -w "$MEDIA" 2>/dev/null | tr -d '\r')
T="$WINEPREFIX/drive_c/swtools"
[ -e "$T/msisql.exe" ] || "$SW_ROOT/install/build-msi-tools.sh"
sql() { "$SW" wine 'C:\swtools\msisql.exe' "$@" 2>/dev/null | tr -d '\r'; }
q() { printf '`%s`' "$1"; }

install_one() { # name dir msi properties
    local name=$1 dir=$2 msi=$3 props=$4 copy="${3%.msi}-wine.msi"
    [ -e "$MEDIA/$dir/$msi" ] || { echo "$name: no $dir/$msi in the media, skipped"; return; }
    [ -e "$MEDIA/$dir/$copy" ] || cp "$MEDIA/$dir/$msi" "$MEDIA/$dir/$copy"
    local M="$WMEDIA\\$dir\\$copy" n=0 a t
    while IFS=$'\t' read -r a t; do
        [ -n "$a" ] || continue
        if [ $((t & 0x400)) -ne 0 ] && [ $((t & 64)) -eq 0 ]; then
            sql "$M" rw "UPDATE $(q CustomAction) SET $(q Type)=$((t | 64)) WHERE $(q Action)='$a'"; n=$((n + 1))
        fi
    done < <(sql "$M" ro "SELECT $(q Action), $(q Type) FROM $(q CustomAction)")
    echo "$name: $n deferred actions set to continue on error"
    printf '@echo off\r\nmsiexec.exe /i "%s" TRANSFORMS="%s\\1033.mst" %s REBOOT=ReallySuppress MSIRESTARTMANAGERCONTROL=Disable /q /norestart /l*v "C:\\swtools\\%s-msi.log"\r\necho msiexec-exit=%%ERRORLEVEL%%\r\n' \
        "$M" "$WMEDIA\\$dir" "$props" "$name" > "$T/$name-msi.bat"
    echo "installing $name..."
    (cd "$T" && "$SW" wine cmd /c "C:\\swtools\\$name-msi.bat" 2>"$T/$name-msi-wine.err" | tr -d '\r' | tail -1)
}

install_one edrawings eDrawings eDrawings.msi \
    'INSTALLDIR="C:\Program Files\SOLIDWORKS Corp\eDrawings\" SHOWLAUNCHREADME=0 SHOWLAUNCHPROGRAM=0 LOGPERFORMANCE=0 LAUNCHPROGRAM=-1 LAUNCHREADME=-1 SLDIM=1 ARPSYSTEMCOMPONENT=1'
install_one fileutilities SWFileUtilities 'SOLIDWORKS File Utilities.msi' \
    'INSTALLDIR="C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS File Utilities\" SLDIM=1 ARPSYSTEMCOMPONENT=1'
