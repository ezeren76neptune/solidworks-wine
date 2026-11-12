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
for src in ntdll_add wininet_setcookieex2; do
    gcc $CFLAGS -c -o build/$src.o $src.c
    ld -nostdlib -T build/flat.ld -o build/$src.elf build/$src.o
    # the blob must be self-contained: no relocations against anything outside it
    if readelf -r build/$src.o | grep -qE 'PLT|GOT'; then echo "$src: external reference" >&2; exit 1; fi
    objcopy -O binary build/$src.elf build/$src.bin
    nm build/$src.elf > build/$src.syms
done
rm -f build/ntdll-*.dll build/wininet-*.dll   # force sw-wine to regenerate the patched DLLs
ls -l build/*.bin
