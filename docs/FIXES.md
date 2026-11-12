# What breaks under Wine, and what fixes it

Every fix that was needed is listed here, grouped by when it bites. "Wine" means Wine 11.20 (Fedora build) unless noted. Several of these are plain gaps in Wine and would be better fixed upstream. If you take one there, please link it here.

## Installing

| Symptom | Cause | Fix |
|---|---|---|
| The installer stub exits at once, asking for "Internet Explorer 10 or later" | The stub checks `GetProcAddress(wininet, "HttpWebSocketReceive")`, and Wine's wininet has no such export | `install/patch-ie10-check.py` flips the one conditional jump after that probe in the staged copies of `setup.exe`, `StartTUI.exe` and `setup_noUAC.exe` |
| The installer aborts on the OS check | It requires Windows 11 | `winetricks win11` (in `setup-prefix.sh`) |
| The installer reports the wrong .NET version | It checks for the .NET 4.8.1 release number | The `Release` value is set to 533320. .NET 4.8 from winetricks runs everything it needs |
| `--multi` answer file is ignored | The file must be a JSON *list* of `{mode, data:{volumes, vars, env}}` | `install/make-install-json.py` |
| .NET install or `ngen` hangs, or the wineserver asserts in `get_server_inproc_sync` | Wine 11's in-process ntsync path under .NET load | `sw-wine` hides `/dev/ntsync` (bubblewrap bind of an unreadable file), so wineserver falls back to server-side synchronisation |
| The VC11 prerequisite step fails | Wine's builtin `msvcr110` and friends have no version resource | `native,builtin` DLL overrides. The installer puts Microsoft's real DLLs in place |
| SOLIDWORKS MSI fails in `InstallSpatialIOP` | The step unzips with the Windows shell's zip-folder API, which Wine lacks | Condition set to `0` in the MSI. `spatialiop.zip` is unpacked with 7z into `SOLIDWORKS\spiop\files` and `Visualize\Plugins\sp.x` |
| SOLIDWORKS MSI rolls back in `SWRegistration` | Some regsvr32 registrations fail under Wine: the property handler, the Design Checker OCX, DFMXpress, and `swdocumentmgr.dll` failing to load | The custom action type gets +64 ("continue on error"): 3073 → 3137 |
| SOLIDWORKS MSI "succeeds" but installs almost nothing | Wine's MSI does not add the parents of the features named in `ADDLOCAL` | `install/install-msis.sh` passes the full feature list a Windows install ends up with (`install/solidworks-addlocal.txt`), via a `.bat` because argv quoting mangles `PROP="a b"` |
| Help, manuals and examples get installed even though Windows skips them | Wine honours `msidbFeatureAttributesFollowParent` differently | `install/feature-fix.sql` clears that flag (attributes 10 → 8) on the 25 features Windows leaves absent |
| Dictionary compile (`JS0CORBADicExe`) fails late in the install | It needs `ntdll!RtlIsNameInExpression`, which no Wine or Proton release has up to 11.20 | Added to the private ntdll copy (`tools/rtl_isnameinexpression.c`), with the DOS wildcard semantics `*`, `?`, `<`, `>` and `"` |

## Starting and signing in

| Symptom | Cause | Fix |
|---|---|---|
| "Missing WebView2 runtime", or a plain Wine username/password box instead of the 3DEXPERIENCE page | No WebView2 runtime in the prefix. The loader looks for `EdgeUpdate\Clients\{F3017226-…}` and `EdgeUpdate\ClientState\{F3017226-…}\EBWebView` | `install/install-webview2.sh`. **Don't type your password into Wine's box.** |
| The WebView2 window is blank, or its GPU process fails | It needs DirectComposition swap chains, and its sandbox fails under Wine | `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--no-sandbox --disable-gpu --disable-gpu-compositing"` (set by `sw-wine`) and `AppDefaults\msedgewebview2.exe\Version=win7` |
| Crash right after sign-in (a jump through a null pointer in `JS0LCC`) | `wininet!InternetSetCookieEx2` is missing, and the launcher uses it to hand the sign-in cookies to WinINet | Added to a private wininet copy (`tools/wininet_setcookieex2.c`), built on Wine's `InternetSetCookieExW` |
| `cannot load JS0PCC.dll`, then a crash in `JS0GROUP` | Dassault's in-memory DLL loader, used for one of its own modules, needs the non-exported Windows loader functions `LdrpHandleTlsData` and `LdrpReleaseTlsEntry`. It finds them by scanning ntdll's code, and Wine's ntdll has neither | `tools/ntdll_add.c` implements both on Wine's own TLS tables (mirroring `alloc_tls_slot` in Wine's `loader.c`). `pe-inject.py --ldrp-tls` lays out the string, the `lea` and the Windows 10 prologue the scanner looks for, each jumping to those implementations. The module itself is not modified, and licensing works exactly as on Windows: you sign in with your account |
| Stuck at "Loading registry…" for minutes | Wine's computer name is the Linux hostname cut to 15 characters. SOLIDWORKS resolves it, and the lookup waits for DNS timeouts | `sw-wine` gives the process tree a hosts file that maps that name to 127.0.0.1 |
| Crash in `comctl32` while "Loading task panes…" | A task pane sends `HDM_LAYOUT` with a NULL `HDLAYOUT`. Windows returns FALSE, while Wine dereferences it | `tools/patch-comctl32.py` adds the NULL check to a copy of `comctl32_v6.dll`. The prefix's winsxs copy is the one Wine maps, so the wrapper binds over both |
| Crash in `concrt140` (`GetProcessorCount` stub) | Wine's concrt140 lacks it | `native,builtin` override for the VC14 runtime. The installer puts Microsoft's DLLs in place |

## Using SOLIDWORKS

| Symptom | Cause | Fix |
|---|---|---|
| The 3D view stays black | With "Enhanced graphics performance" on, SOLIDWORKS makes OpenGL calls with no current context | Turn it off: Tools > Options > Performance |
| Hang with an `X_CopyArea BadMatch` error (seen on NVIDIA), or a black view | EGL backend of Wine's X11 driver | `X11 Driver\UseEGL=N` (GLX) |
| The PropertyManager's green check and other buttons do nothing | Wine sends `WM_CAPTURECHANGED` to a window that keeps the capture. The buttons' subclass then drops the click between button-down and button-up (Wine bugs 27403, 58668, 59478) | `tools/patch-win32u.py` applies Denis Bonnenfant's patch from bug 27403 in binary form: in `set_capture_window`, skip the message when the previous window is the same one |
| No shaded faces on NVIDIA (edges only) | Unknown. Seen with PRIME render offload on an RTX 3070 | Use the integrated GPU, which is the default. `SW_GPU=nvidia` exists for testing |
| The Open dialog's left pane shows Wine's My Computer, Trash and "/" instead of your folders | Wine's dialog builds that pane from the desktop namespace. Windows-style "folder shortcut" namespace items (`Instance\InitPropertyBag\Target`) are ignored by Wine's shell32 | `tools/swplaces.c` is a small COM DLL that serves such items using Wine's own FolderShortcut class. `tools/sync-places.py` registers your file manager's places and hides Wine's items (`SFGAO_NONENUMERATED`) |
| Double-clicking a part in the file manager doesn't start SOLIDWORKS properly | Wine's file associations call plain `wine` | `install/fix-desktop-entries.sh` |

## How the patched files are made

`sw-wine` never touches the system's Wine. On each start it:

1. hashes the system's `ntdll.dll`, `wininet.dll`, `comctl32_v6.dll` and `win32u.so`;
2. builds a patched copy of each into `tools/build/` the first time a hash is seen;
3. bind-mounts each copy over the original, for the SOLIDWORKS process tree only, through bubblewrap.

After a Wine update, new copies are made automatically. The patchers look for exact byte patterns. If a pattern is missing in a new Wine build, the patcher refuses and writes nothing. The wrapper then goes on without that fix, except for ntdll, where it stops, so check its output.

- `tools/build.sh` compiles `ntdll_add.c` and `wininet_setcookieex2.c` as freestanding, position-independent blobs: no imports, `-fPIE`, a flat linker script.
- `tools/pe-inject.py` adds such a blob to a PE DLL. It puts the blob in a new `.swx` section and rebuilds the export directory. It also fills "slots" in the blob with the distance to DLL exports (`slot_<name>`) or to internal symbols from the DLL's COFF symbol table (`symslot_<name>`). The blob can then call into the DLL without relocations.

Tests (Windows programs, built with the prefix's `csc.exe` or MinGW) are in `tools/tests/`:

- `rtltest` checks `RtlIsNameInExpression`;
- `cookietest` checks `InternetSetCookieEx2`;
- `tlstest` checks the TLS functions; pass it a DLL that has a TLS directory;
- `placestest` checks the file-dialog places.
