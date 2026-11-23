#!/bin/bash
# Build the code blobs that sw-wine injects into private copies of Wine's DLLs.
# Output: build/<name>.bin (flat code) and build/<name>.syms (nm listing).
set -e
cd "$(dirname "$0")"
mkdir -p build
cat > build/flat.ld <<'EOF'
SECTIONS { . = 0; .text : { *(.text*) *(.rodata*) } /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) } }
EOF
CFLAGS="-Os -ffreestanding -fno-builtin -fno-tree-loop-distribute-patterns -fno-stack-protector
        -fno-asynchronous-unwind-tables -fno-unwind-tables -fcf-protection=none -fno-jump-tables
        -mgeneral-regs-only -mno-red-zone -fPIE -fvisibility=hidden -Wall -Wno-array-bounds"
# blob: sources
for spec in "ntdll_add: ntdll_add" "wininet_add: wininet_setcookieex2 wininet_errordlg" "shell32_add: shell32_openfolder" "uxtheme_add: uxtheme_parentbg"; do
    blob=${spec%%:*} objs=()
    for src in ${spec#*:}; do
        gcc $CFLAGS -c -o build/$src.o $src.c
        # the blob must be self-contained: no relocations against anything outside it
        # (and no absolute addresses, e.g. pointer tables: the blob is never relocated)
        if readelf -r build/$src.o | grep -qE 'PLT|GOT|R_X86_64_64|R_X86_64_32'; then
            echo "$src: external reference or absolute address" >&2; exit 1
        fi
        objs+=(build/$src.o)
    done
    ld -nostdlib -T build/flat.ld -o build/$blob.elf "${objs[@]}"
    objcopy -O binary build/$blob.elf build/$blob.bin
    nm build/$blob.elf > build/$blob.syms
done
# sw-wine keys the patched DLLs on the blob, so changed blobs regenerate them
ls -l build/*.bin
