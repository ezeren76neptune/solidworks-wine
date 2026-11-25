#!/bin/bash
# Install the SOLIDWORKS MSI from SOLIDWORKS Installation Manager media (a serial-number licence,
# docs/INSTALL-STANDALONE.md) with msiexec, after the Installation Manager's own attempt stopped
# with "Unzip failed" (MSI error 1603).
#   install/install-sim-msi.sh "<media folder>"      e.g. ~/Downloads/SOLIDWORKS Downloads/SOLIDWORKS 2026 SP05.2
# The serial comes from $SW_SERIAL or a hidden prompt and is never printed; the .bat that passes it
# to msiexec is deleted afterwards (the verbose MSI log in C:\swtools still records it, so keep that
# log to yourself). Needs C:\swtools\msisql.exe (install/build-msi-tools.sh) and 7z.
#
# Works on a copy, swwi\data\solidworks-wine.msi, next to the original so its cabinets resolve:
#   * InstallSpatialIOP off; spatialiop.zip is unpacked with 7z instead (Wine has no shell zip API);
#   * SWRegistration continues on error (some regsvr32 registrations fail under Wine);
#   * the Toolbox/Hole Wizard steps SldToolboxUpdater, UpdateBrowserData and WriteToolboxStandardsXML
#     continue on error: they run DatabaseConverter.exe (32-bit .NET), which dies under Wine in
#     Process.MainModule and rolled the whole install back. The Hole Wizard database
#     (C:\SOLIDWORKS Data\lang\english\swbrowser.sldedb) is installed anyway;
#   * install/feature-fix.sql (no "follow parent" language and help extras).
# ADDLOCAL = the features the Installation Manager asks for (SW_ADDLOCAL_BASE), their parents and
# follow-parent children, plus install/solidworks-addlocal.txt (what a Windows install ends up
# with); Wine's MSI adds no parent features by itself.
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
SW="$SW_ROOT/bin/sw-wine"
MEDIA="$(readlink -f "${1:?usage: install-sim-msi.sh <Installation Manager media folder>}")"
DATA="$MEDIA/swwi/data"
[ -e "$DATA/solidworks.msi" ] || { echo "no swwi/data/solidworks.msi in $MEDIA" >&2; exit 1; }
WDATA=$("$SW" wine winepath -w "$DATA" 2>/dev/null | tr -d '\r')
T="$WINEPREFIX/drive_c/swtools"
[ -e "$T/msisql.exe" ] || "$SW_ROOT/install/build-msi-tools.sh"
BASE="${SW_ADDLOCAL_BASE:-FeatureWorks,SolidWorksUtilities,CoreSolidWorksTaskScheduler,ExampleFiles,Manuals,HelpFiles}"
sql() { "$SW" wine 'C:\swtools\msisql.exe' "$@" 2>/dev/null | tr -d '\r'; }
q() { printf '`%s`' "$1"; }

[ -e "$DATA/solidworks-wine.msi" ] || cp "$DATA/solidworks.msi" "$DATA/solidworks-wine.msi"
M="$WDATA\\solidworks-wine.msi"
sql "$M" rw "UPDATE $(q InstallExecuteSequence) SET $(q Condition)='0' WHERE $(q Action)='InstallSpatialIOP'"
for a in SWRegistration SldToolboxUpdater UpdateBrowserData WriteToolboxStandardsXML; do
    t=$(sql "$M" ro "SELECT $(q Type) FROM $(q CustomAction) WHERE $(q Action)='$a'" | head -1)
    if [ -n "$t" ] && [ $((t & 64)) -eq 0 ]; then
        sql "$M" rw "UPDATE $(q CustomAction) SET $(q Type)=$((t | 64)) WHERE $(q Action)='$a'"
    fi
done
mapfile -t FIX < "$SW_ROOT/install/feature-fix.sql"
sql "$M" rw "${FIX[@]}"
echo "patched solidworks-wine.msi"

SPIOP="$WINEPREFIX/drive_c/Program Files/SOLIDWORKS Corp/SOLIDWORKS/spiop/files"
mkdir -p "$SPIOP"
if command -v 7z >/dev/null; then 7z x -y -bso0 -bsp0 -o"$SPIOP" "$DATA/spatialiop.zip"; else unzip -q -o "$DATA/spatialiop.zip" -d "$SPIOP"; fi
echo "unpacked spatialiop.zip"

sql "$M" ro "SELECT $(q Feature), $(q Feature_Parent), $(q Level), $(q Attributes) FROM $(q Feature)" > "$T/features.tsv"
ADDLOCAL=$(python3 -I - "$T/features.tsv" "$SW_ROOT/install/solidworks-addlocal.txt" "$BASE" <<'EOF'
import sys
feat = {}
for l in open(sys.argv[1]):
    r = l.rstrip('\n').split('\t')
    if len(r) >= 4 and r[0]:
        feat[r[0]] = (r[1], int(r[3] or 0))
S = {f for f in sys.argv[3].split(',') if f in feat}
for f in list(S):                                   # parents
    while feat[f][0] and feat[f][0] != f and feat[f][0] in feat:
        f = feat[f][0]; S.add(f)
changed = True
while changed:                                      # follow-parent children
    changed = False
    for f, (p, att) in feat.items():
        if f not in S and p in S and att & 2:
            S.add(f); changed = True
S |= {g.strip() for g in open(sys.argv[2]) if g.strip() in feat}
print(','.join(sorted(S)))
EOF
)
echo "ADDLOCAL: $(tr ',' '\n' <<< "$ADDLOCAL" | wc -l) features"

SN="${SW_SERIAL:-}"
[ -n "$SN" ] || { read -rsp 'SOLIDWORKS serial (hidden): ' SN; echo; }
SN=$(tr -cd '0-9A-Za-z' <<< "$SN" | tr a-z A-Z)
[ ${#SN} -eq 24 ] || { echo "a SOLIDWORKS serial has 24 letters and digits" >&2; exit 1; }
BAT="$T/sw-sim-msi.bat"
trap 'rm -f "$BAT"' EXIT
printf '@echo off\r\nmsiexec.exe /i "%s" TRANSFORMS="%s\\1033.mst" INSTALLDIR="C:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS\\" ADDLOCAL=%s SLDIM=1 REBOOT=ReallySuppress MSIRESTARTMANAGERCONTROL=Disable TOOLBOXFOLDER="C:\\SOLIDWORKS Data\\" OFFICEOPTION=0 ARPSYSTEMCOMPONENT=1 SOLIDWORKSSERIALNUMBER=%s /q /norestart /l*v "C:\\swtools\\solidworks-sim-msi.log"\r\necho msiexec-exit=%%ERRORLEVEL%%\r\n' \
    "$M" "$WDATA" "$ADDLOCAL" "$SN" > "$BAT"
unset SN
echo "installing SOLIDWORKS (several minutes)..."
(cd "$T" && "$SW" wine cmd /c 'C:\swtools\sw-sim-msi.bat' 2>"$T/solidworks-sim-msi-wine.err" | tr -d '\r' | tail -1)
echo "msiexec-exit=0 means installed; otherwise see C:\\swtools\\solidworks-sim-msi.log and solidworks-sim-msi-wine.err"
