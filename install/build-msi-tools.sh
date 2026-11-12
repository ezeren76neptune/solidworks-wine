#!/bin/bash
# Build the two small MSI tools (msisql, msifeat) with the prefix's own C#
# compiler (.NET Framework 4.8) into C:\swtools.
set -euo pipefail
SW_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$SW_ROOT/prefix}"
D="$WINEPREFIX/drive_c/swtools"
mkdir -p "$D"
cp "$SW_ROOT/tools/msisql.cs" "$SW_ROOT/tools/msifeat.cs" "$D/"
cd "$D"
for t in msisql msifeat; do
    "$SW_ROOT/bin/sw-wine" wine 'C:\windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe' \
        /nologo /platform:x64 /out:$t.exe $t.cs | tr -d '\r'
    [ -e "$t.exe" ] || { echo "building $t failed" >&2; exit 1; }
done
echo "built C:\\swtools\\msisql.exe and msifeat.exe"
