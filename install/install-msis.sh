#!/bin/bash
# Install the SOLIDWORKS and Visualize MSIs directly with msiexec, after
# install/patch-msis.sh.
#   install/install-msis.sh
# Wine's MSI does not pull in the parents of the features the Dassault installer
# asks for, so it would install almost nothing; this passes the full list of
# features a Windows install ends up with (install/solidworks-addlocal.txt).
# The command lines go through .bat files because quoting PROP="a b" through
# Wine's argv handling breaks them. Logs: C:\swtools\*-msi.log
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
SW="$SW_ROOT/bin/sw-wine"
D="$WINEPREFIX/drive_c/swtools"
mkdir -p "$D"
R='C:\Program Files\Dassault Systemes\SOLIDWORKS 3DEXPERIENCE R2026x'
M="$R\\win_b64\\resources\\MSI"
COMMON='SWXIM=1 SLDIM=1 ARPSYSTEMCOMPONENT=1 REBOOT=ReallySuppress MSIRESTARTMANAGERCONTROL=Disable'
ADDLOCAL=$(grep -v '^\s*$' "$SW_ROOT/install/solidworks-addlocal.txt" | paste -sd,)

bat() { # name command...
    printf '@echo off\r\n%s\r\necho msiexec-exit=%%ERRORLEVEL%%\r\n' "$2" > "$D/$1.bat"
    (cd "$D" && "$SW" wine cmd /c "C:\\swtools\\$1.bat" | tr -d '\r' | tail -1)
}

echo "installing SOLIDWORKS (several minutes)..."
bat solidworks-msi "msiexec.exe /i \"$M\\SolidWorks\\solidworks.msi\" TRANSFORMS=\"$M\\SolidWorks\\1033.mst\" INSTALLDIR=\"$R\\SOLIDWORKS\" $COMMON TOOLBOXFOLDER=\"C:\\users\\Public\\Documents\\SOLIDWORKS\\SOLIDWORKS Data\" ADDLOCAL=$ADDLOCAL OFFICEOPTION=3 /q /norestart /l*v \"C:\\swtools\\solidworks-msi.log\""

if [ -e "$WINEPREFIX/drive_c/Program Files/Dassault Systemes/SOLIDWORKS 3DEXPERIENCE R2026x/win_b64/resources/MSI/Visualize/SOLIDWORKS Visualize.msi" ]; then
    echo "installing SOLIDWORKS Visualize..."
    bat visualize-msi "msiexec.exe /i \"$M\\Visualize\\SOLIDWORKS Visualize.msi\" TRANSFORMS=\"$M\\Visualize\\1033.mst\" INSTALLDIR=\"$R\\Visualize\" $COMMON /q /norestart /l*v \"C:\\swtools\\visualize-msi.log\""
fi
echo "msiexec-exit=0 means installed; otherwise see the log. Next: install/run-installer.sh again."
