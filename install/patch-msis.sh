#!/bin/bash
# Fix the SOLIDWORKS and Visualize MSIs (in the installer's resources folder)
# so they install under Wine, and unpack the Spatial import/export libraries
# that their InstallSpatialIOP step would have unpacked.
#   install/patch-msis.sh
# Run it once the installer has put win_b64\resources\MSI in place (after its
# first run stops at SOLIDWORKS). Safe to re-run. Needs C:\swtools\msisql.exe
# (install/build-msi-tools.sh) and 7z or unzip.
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
SW="$SW_ROOT/bin/sw-wine"
T="$WINEPREFIX/drive_c/Program Files/Dassault Systemes/SOLIDWORKS 3DEXPERIENCE R2026x"
WT='C:\Program Files\Dassault Systemes\SOLIDWORKS 3DEXPERIENCE R2026x'
[ -e "$WINEPREFIX/drive_c/swtools/msisql.exe" ] || "$SW_ROOT/install/build-msi-tools.sh"
sql() { "$SW" wine 'C:\swtools\msisql.exe' "$@" | tr -d '\r'; }
unpack() { # zip dir
    mkdir -p "$2"
    if command -v 7z >/dev/null; then 7z x -y -bso0 -bsp0 -o"$2" "$1"; else unzip -q -o "$1" -d "$2"; fi
}
q() { printf '`%s`' "$1"; }   # MSI SQL quotes identifiers with backticks

SWMSI="$T/win_b64/resources/MSI/SolidWorks/solidworks.msi"
if [ -e "$SWMSI" ]; then
    M="$WT\\win_b64\\resources\\MSI\\SolidWorks\\solidworks.msi"
    # 1. InstallSpatialIOP unzips through the shell's zip folder API, which Wine lacks.
    sql "$M" rw "UPDATE $(q InstallExecuteSequence) SET $(q Condition)='0' WHERE $(q Action)='InstallSpatialIOP'"
    # 2. SWRegistration (deferred regsvr32 of a few shell extensions/OCXs) fails under
    #    Wine and rolls the whole install back: make it continue on error (+64).
    t=$(sql "$M" ro "SELECT $(q Type) FROM $(q CustomAction) WHERE $(q Action)='SWRegistration'" | head -1)
    if [ -n "$t" ] && [ $((t & 64)) -eq 0 ]; then
        sql "$M" rw "UPDATE $(q CustomAction) SET $(q Type)=$((t | 64)) WHERE $(q Action)='SWRegistration'"
    fi
    # 3. Wine's MSI installs "follow parent" features that Windows leaves out
    #    (help, manuals, examples); clear that flag on them.
    mapfile -t FIX < "$SW_ROOT/install/feature-fix.sql"
    sql "$M" rw "${FIX[@]}"
    unpack "$T/win_b64/resources/MSI/SolidWorks/spatialiop.zip" "$T/SOLIDWORKS/spiop/files"
    echo "patched solidworks.msi, unpacked SOLIDWORKS\\spiop\\files"
else
    echo "no solidworks.msi yet: run install/run-installer.sh first" >&2
fi

VZMSI="$T/win_b64/resources/MSI/Visualize/SOLIDWORKS Visualize.msi"
if [ -e "$VZMSI" ]; then
    M="$WT\\win_b64\\resources\\MSI\\Visualize\\SOLIDWORKS Visualize.msi"
    sql "$M" rw "UPDATE $(q InstallExecuteSequence) SET $(q Condition)='0' WHERE $(q Action)='InstallSpatialIOP'"
    unpack "$T/win_b64/resources/MSI/Visualize/spatialiop.zip" "$T/Visualize/Plugins/sp.x"
    echo "patched SOLIDWORKS Visualize.msi, unpacked Visualize\\Plugins\\sp.x"
fi
