#!/bin/bash
# Make WPF programs such as eDrawings start and draw in the prefix.
#   install/wpf-fixes.sh
# 1. PresentationFramework.Aero2 (the Windows 8+ WPF theme assembly) is not part of the .NET 4.8
#    that winetricks installs; eDrawings stops with "Could not load file or assembly
#    'PresentationFramework.Aero2'". It is taken, Microsoft-signed, from the Windows 10 package
#    inside the .NET 4.8 installer winetricks cached, and put into the GAC and the WPF folders.
# 2. WPF draws through Direct3D 9; with DXVK as Wine's d3d9 (as Fedora ships it) the window stays
#    black. HKCU\Software\Microsoft\Avalon.Graphics\DisableHWAcceleration=1 makes WPF draw in
#    software. SOLIDWORKS' own WPF panes are fine with that.
# Needs 7z and the cached installer (~/.cache/winetricks/dotnet48, from install/setup-prefix.sh).
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
SW="$SW_ROOT/bin/sw-wine"
NDP="${XDG_CACHE_HOME:-$HOME/.cache}/winetricks/dotnet48/ndp48-x86-x64-allos-enu.exe"
NET="$WINEPREFIX/drive_c/windows/Microsoft.NET"
GAC="$NET/assembly/GAC_MSIL/PresentationFramework.Aero2/v4.0_4.0.0.0__31bf3856ad364e35"

if [ ! -e "$GAC/PresentationFramework.Aero2.dll" ]; then
    [ -e "$NDP" ] || { echo "no cached $NDP: run install/setup-prefix.sh (winetricks dotnet48) first" >&2; exit 1; }
    TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
    7z e -y -bso0 -bsp0 -o"$TMP" "$NDP" 'x64-Windows10.0-KB4486153-x64.cab' >/dev/null
    7z e -y -bso0 -bsp0 -o"$TMP" "$TMP/x64-Windows10.0-KB4486153-x64.cab" \
        'msil_presentationframework.aero2_31bf3856ad364e35_4.0.15744.161_none_c2ca91021c095a55/presentationframework.aero2.dll' >/dev/null
    DLL="$TMP/presentationframework.aero2.dll"
    [ -s "$DLL" ] || { echo "PresentationFramework.Aero2 not found in $NDP" >&2; exit 1; }
    mkdir -p "$GAC"
    cp "$DLL" "$GAC/PresentationFramework.Aero2.dll"
    for d in "$NET/Framework/v4.0.30319/WPF" "$NET/Framework64/v4.0.30319/WPF"; do
        [ -d "$d" ] && cp "$DLL" "$d/PresentationFramework.Aero2.dll"
    done
    echo "installed PresentationFramework.Aero2"
fi
"$SW" wine reg add 'HKCU\Software\Microsoft\Avalon.Graphics' /v DisableHWAcceleration /t REG_DWORD /d 1 /f >/dev/null 2>&1
echo "WPF draws in software (Avalon.Graphics\\DisableHWAcceleration=1)"
