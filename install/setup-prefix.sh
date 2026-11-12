#!/bin/bash
# Create and configure the Wine prefix SOLIDWORKS is installed into.
#   install/setup-prefix.sh            (prefix: <repo>/prefix, or $WINEPREFIX)
# Safe to re-run: every step only sets things. Needs winetricks; downloads
# .NET Framework 4.8, core fonts and MSXML 6 from Microsoft (winetricks caches them).
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
SW="$SW_ROOT/bin/sw-wine"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
command -v winetricks >/dev/null || { echo "winetricks is required" >&2; exit 1; }
[ -e "$SW_ROOT/tools/build/ntdll_add.bin" ] || "$SW_ROOT/tools/build.sh"

step() { printf '\n== %s\n' "$*"; }
reg() { "$SW" wine reg add "$@" /f >/dev/null; }

step "creating $WINEPREFIX"
"$SW" wineboot -i
"$SW" wineserver -w

# Everything goes through sw-wine: with /dev/ntsync visible, Wine 11's in-process
# sync asserts under .NET load and the .NET install hangs in ngen.
step ".NET Framework 4.8"
"$SW" winetricks -q dotnet48
"$SW" wineserver -w
step "core fonts, MSXML 6"
"$SW" winetricks -q corefonts msxml6
# The Dassault installer aborts on anything older than Windows 11.
step "Windows 11"
"$SW" winetricks -q win11

step "registry settings"
# The installer wants .NET 4.8.1 (release 533320); 4.8 runs everything it needs.
for k in 'HKLM\Software\Microsoft\NET Framework Setup\NDP\v4\Full' \
         'HKLM\Software\Wow6432Node\Microsoft\NET Framework Setup\NDP\v4\Full'; do
    reg "$k" /v Release /t REG_DWORD /d 533320
done
# Use Microsoft's Visual C++ runtimes, which the installer puts in place, not
# Wine's: Wine's VC11 stubs have no version resource (the VC11 prerequisite
# step fails) and its concrt140 lacks GetProcessorCount.
for d in msvcr110 msvcp110 atl110 vcomp110 concrt140 msvcp140 msvcp140_1 msvcp140_2 \
         msvcp140_atomic_wait msvcp140_codecvt_ids vcruntime140 vcruntime140_1 vcomp140 \
         vccorlib140 vcamp140; do
    reg 'HKCU\Software\Wine\DllOverrides' /v "$d" /d native,builtin
done
# GLX instead of EGL for OpenGL: with EGL the viewport stayed black or hung.
reg 'HKCU\Software\Wine\X11 Driver' /v UseEGL /d N
# SOLIDWORKS' helpers crash-probe a lot; don't pop up Wine's crash dialog.
reg 'HKCU\Software\Wine\WineDbg' /v ShowCrashDialog /t REG_DWORD /d 0
# The WebView2 sign-in page started only with this.
reg 'HKCU\Software\Wine\AppDefaults\msedgewebview2.exe' /v Version /d win7
"$SW" wineserver -w
step "done: $WINEPREFIX"
