# Troubleshooting

Start with logs. Prefix the command with `WINEDEBUG=err+all,warn+module`, or a channel list such as `+loaddll,+seh`:

```bash
WINEDEBUG=err+all,warn+module bin/sw-wine wine 'C:\users\Public\Desktop\SOLIDWORKS Design.lnk' 2>&1 | tee sw.log
```

Dassault's own logs are in:

- `prefix/drive_c/users/<you>/AppData/Local/DassaultSystemes/CATTemp/` (`AbendTrace_*` files after a crash);
- `…\SOLIDWORKS 3DEXPERIENCE R2026x\InstallData\log\` for the installer.

**Before you post one of these logs, remove your sign-in tickets and cookies from it.**

| What you see | Look at |
|---|---|
| Started from an icon, SOLIDWORKS fails where `bin/sw-wine` works | The icon uses plain `wine`. Run `install/fix-desktop-entries.sh` |
| `sw-wine: run tools/build.sh first` | Run `tools/build.sh` (needs gcc and binutils) |
| `sw-wine: set SW_WINE_PE …` | Your Wine is somewhere unusual. Point `SW_WINE_PE` at its `x86_64-windows` folder (the one with `ntdll.dll`) |
| A patcher says "not found" or "unexpected …" | Your Wine build differs from the tested one. That fix is skipped, or for ntdll the wrapper stops. See [FIXES.md](FIXES.md) for what the patch does, so it can be ported |
| `pe-inject: … symbol` errors | Your Wine's PE DLLs have no COFF symbol table (some distros strip them). The TLS fix needs `tls_dirs` and `tls_module_count` from it |
| Grey Wine username/password box | WebView2 is missing or not registered: redo `install/install-webview2.sh`. Don't enter your password into that box. If you did and ticked "save", the password is stored in the prefix |
| `cannot load JS0PCC.dll` | The patched ntdll isn't in use. Did you start with plain `wine`? |
| Stuck at "Loading registry…" | The first 15 characters of `hostname -s` must resolve. The wrapper adds them to the hosts file it uses. Check `tools/build/.hosts` |
| NVIDIA mode starts on the integrated GPU, with a "NVIDIA mode unavailable" notification | After a Wine update, the NVIDIA patches (`tools/patch-win32u-nvidia.py`, `tools/patch-win32u-memdc.py`) didn't fit the new `win32u.so`, so the wrapper fell back instead of starting a session whose 3D view never updates. Run the patchers by hand on `tools/build/win32u-<hash>.so` to see which pattern they missed |
| NVIDIA mode: the 3D view freezes or never updates | The patched `win32u.so` isn't in use: start with `SW_GPU=nvidia`, after closing every SOLIDWORKS and Wine process (`bin/sw-wine wineserver -k`). Look for a `patch-win32u` message in the wrapper's output. Check with `nvidia-smi` that `sldworks.exe` is listed |
| NVIDIA mode: dragging a dimension or a selection box leaves copies of it behind | The wrapper didn't set `DisabledExtensions` (see [FIXES.md](FIXES.md)). Check with `bin/sw-wine wine reg query 'HKCU\Software\Wine\AppDefaults\sldworks.exe\OpenGL'`, then restart SOLIDWORKS |
| Black 3D view | Enhanced graphics performance is on (Tools > Options > Performance), or Wine is using EGL (`setup-prefix.sh` sets `X11 Driver\UseEGL=N`) |
| Green check / OK buttons do nothing | The win32u patch isn't applied. Look for a `patch-win32u` message in the wrapper's output |
| A "no license" error on the next start | Seen once, after a start that had crashed. Stopping everything with `bin/sw-wine wineserver -k` and starting again got past it |
| "Segoe UI is not available" when opening parts | The font replacements are missing from the prefix (older installs): re-run the font lines of `install/setup-prefix.sh`. The message itself is harmless |
| Typing in a PropertyManager box keeps only the first character | The patched `winex11.so` isn't in use: look for a `patch-winex11-focus` message in the wrapper's output |
| Open/Save show Wine's dialog instead of KDE's | `tools/build/swfiledlg.dll` is missing (run `tools/build-pe.sh`), `kdialog` isn't installed, or `SW_FILEDLG=wine` is set. The wrapper re-registers the DLL on the next start |
| `wineserver -w` never returns | Expected once the 3DEXPERIENCE Launcher service runs. Use `bin/sw-wine wineserver -k` |
| The installer stops on an MSI other than SOLIDWORKS | Find the failing action in the MSI log (`/l*v`). The tools `C:\swtools\msisql.exe` and `msifeat.exe` (from `install/build-msi-tools.sh`) can query and edit MSI tables under Wine, as `install/patch-msis.sh` does |
