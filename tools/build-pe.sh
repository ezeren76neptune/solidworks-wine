#!/bin/bash
# Build the Windows-side helpers (build/swplaces.dll, build/swfiledlg.dll, build/swopenfolder.exe) with MinGW in a Fedora container,
# so nothing has to be installed on the host. The image is built once and reused.
set -e
cd "$(dirname "$0")"
mkdir -p build
IMAGE=localhost/sw-mingw:44
if ! podman image exists "$IMAGE"; then
    printf 'FROM registry.fedoraproject.org/fedora:44\nRUN dnf -y -q install mingw64-gcc && dnf clean all\n' |
        podman build -q -t "$IMAGE" -f - . >/dev/null
fi
cat > build/swplaces.def <<'EOF'
LIBRARY swplaces
EXPORTS
    DllGetClassObject PRIVATE
    DllCanUnloadNow PRIVATE
EOF
# --userns=keep-id: output files stay owned by this user; label=disable: no SELinux relabel of the tree
podman run --rm --userns=keep-id --security-opt label=disable -v "$PWD:/src" -w /src "$IMAGE" \
    x86_64-w64-mingw32-gcc -O2 -Wall -shared -s -static-libgcc -Wl,--no-insert-timestamp -o build/swplaces.dll \
        swplaces.c build/swplaces.def -lole32 -luuid -ladvapi32
ls -l build/swplaces.dll
cat > build/swfiledlg.def <<'EOF'
LIBRARY swfiledlg
EXPORTS
    DllGetClassObject PRIVATE
    DllCanUnloadNow PRIVATE
EOF
podman run --rm --userns=keep-id --security-opt label=disable -v "$PWD:/src" -w /src "$IMAGE" \
    x86_64-w64-mingw32-gcc -O2 -Wall -shared -s -static-libgcc -Wl,--no-insert-timestamp -o build/swfiledlg.dll \
        swfiledlg.c build/swfiledlg.def -lshell32 -lshlwapi -lole32 -luuid -luser32
ls -l build/swfiledlg.dll
podman run --rm --userns=keep-id --security-opt label=disable -v "$PWD:/src" -w /src "$IMAGE" \
    x86_64-w64-mingw32-gcc -O2 -Wall -s -municode -mwindows -static-libgcc -Wl,--no-insert-timestamp -o build/swopenfolder.exe \
        swopenfolder.c -lshell32
ls -l build/swopenfolder.exe
