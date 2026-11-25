# Installing SOLIDWORKS with a serial number (standalone licence)

This is the second install path: classic desktop SOLIDWORKS, installed with the **SOLIDWORKS Installation Manager** and activated with a **serial number**, the kind of licence a company buys from a reseller. The [main guide](INSTALL.md) covers 3DEXPERIENCE SOLIDWORKS for Makers, which signs in instead. Both can live side by side in separate Wine prefixes.

Tested once, end to end, on Fedora 44 KDE with Wine 11.21:

| | |
|---|---|
| Installed | SOLIDWORKS Design **Standard** 2026 SP5.2 (standalone serial, 9000…), eDrawings 2026, SOLIDWORKS File Utilities, and the prerequisites the Installation Manager installs itself (Visual C++ 2022, .NET 4.8.1, VSTA, VBA 7.1, Windows Performance Toolkit, CEF, Login Manager) |
| Works | Activation over the Internet; licence agreement; new part, sketch, extrude in a shaded view on the integrated GPU (the "Enhanced graphics performance" change from the main guide was not needed); the API (VBScript, `CreateObject("SldWorks.Application")`); eDrawings opening a part in 3D |
| Not tested | Network (SolidNetWork) licences, Professional/Premium, Simulation, CAM, PDM, Visualize, Toolbox, deactivating/transferring the licence, the NVIDIA mode with this install |

Everything below comes from that one install. Expect to read logs.

## 0. What you need

- The packages from the main guide, plus `7z`. For step 6's optional terminal control, the Python package `websockets`.
- The installer, `SolidWorksSetup_<version>.exe`, from the SOLIDWORKS downloads page. The page only offers it when your SOLIDWORKS ID is linked to the company that owns the licence; your reseller can do that.
- The serial number (24 characters, starting with 9000 for a standalone licence). If the licence is still activated on another computer, deactivate it there first, or ask the reseller to reset it.

## 1. Build the tools and make the prefix

```bash
tools/build.sh && tools/build-pe.sh       # the Wine additions, and autoattach.exe (step 3)
export WINEPREFIX=~/solidworks-wine/prefix-standalone   # a prefix of its own
install/setup-prefix.sh
install/install-webview2.sh <WebView2 runtime folder or .cab>   # the tested setup used 157.0.4341.42
```

Use the same `WINEPREFIX` for every command below.

## 2. Unpack the installer

```bash
bin/sw-wine wine /path/to/SolidWorksSetup_2026_SP5.2.exe
```

It is a WinZip self-extractor: press **Unzip**. It unpacks to `C:\swdist\SOLIDWORKS_<version>\` and starts `sldim\sldIM.exe`, the Installation Manager. **The Installation Manager is a 32-bit program**: it uses Wine's 32-bit `wininet.dll`, which `sw-wine` patches as well (step 4).

What happens next, every time it starts, is expected:

1. It decides its first WebView2 page "failed to connect" (WebView2 is slow to start under Wine), runs the WebView2 installer it ships (version 119, about a minute, behind a "Please wait while Microsoft WebView2 Runtime is installed" box), and then rebuilds its page. Wait for that. The newer runtime from step 1 stays registered.
2. That WebView2 installer may queue a delete-on-reboot entry. The next start then says **"A Windows reboot is pending from a previous installation"**. Wine has no reboots: remove the entry and press OK:

   ```bash
   bin/sw-wine wine reg delete 'HKLM\System\CurrentControlSet\Control\Session Manager' /v PendingFileRenameOperations /f
   ```

   Don't run `wineboot -r` for it: the queued entry deletes the WebView2 folder.
3. If it says **"Cannot start SOLIDWORKS Installation Manager without Microsoft WebView2 runtime"**, the page rebuild failed. Close it and start `C:\swdist\…\sldim\sldIM.exe` again.

## 3. Typing into the pages: autoattach

The pages are WebView2 drawn inside the Installation Manager's window by another process (`msedgewebview2.exe`). Windows joins the keyboard input of the two programs when one's window holds the other's; Wine doesn't, so clicks work but typed text never arrives, the serial boxes in particular. Run this while the Installation Manager is open:

```bash
bin/sw-wine wine tools/build/autoattach.exe &
```

It joins them the way Windows would (it prints each `attach …: ok`). See [FIXES.md](FIXES.md#serial-number-installs).

## 4. Serial number and server check

Choose **Install on this computer**, **Next**, type the serial into the six boxes under SOLIDWORKS Design, **Next**. It then asks Dassault's server what you may install.

**"Could not connect to the SOLIDWORKS server to determine which products you are entitled to install"** with a working network means the unpatched 32-bit `wininet.dll` is loaded: the server's answer arrives, and Wine throws it away (see [FIXES.md](FIXES.md#serial-number-installs)). Close everything with `bin/sw-wine wineserver -k`, check that the wrapper printed `InternetSetFilePointer keeps buffered data (32-bit …)`, and start again.

## 5. Products, download, install

On the **Summary** page:

- **Products > Change**: what your licence covers. The tested install kept SOLIDWORKS Design, eDrawings and File Utilities, and left out Composer Player, CAM and the two 3DEXPERIENCE add-ons.
- **Download Options > Change**: "Download and install"; untick the background downloader.
- Accept the licence agreement, then **Download and Install**. It downloads into `C:\users\<you>\Downloads\SOLIDWORKS Downloads\SOLIDWORKS <version>` (Wine links that to your Linux Downloads folder): about 4.4 GB for those products.

In the tested install the Installation Manager crashed right after the download finished (a null read). Starting `sldim\sldIM.exe` **from the download folder** and going through the pages again installed from the downloaded files. It forgets the product choices, so set them again.

It then installs the prerequisites, which all worked, and stops on SOLIDWORKS Design with **"Unzip failed"**. That is the SOLIDWORKS MSI's `InstallSpatialIOP` step, the same as in the main guide. Press OK. On the results page untick "Send installation logs", press **Finish**, then decline the Customer Experience programme and **Finish** again. Then install it yourself:

```bash
install/install-sim-msi.sh "$HOME/Downloads/SOLIDWORKS Downloads/SOLIDWORKS 2026 SP05.2"
```

It patches a copy of the MSI, unpacks the Spatial libraries and runs msiexec with the full feature list and your serial (hidden prompt, or `SW_SERIAL`). `msiexec-exit=0` means installed; it takes a few minutes and installs about 8 GB. The script explains each change. The serial ends up in the MSI log `C:\swtools\solidworks-sim-msi.log` (MSI logs record properties), so don't post that log as is.

eDrawings and File Utilities, which the Installation Manager never got to:

```bash
install/install-sim-extras.sh "$HOME/Downloads/SOLIDWORKS Downloads/SOLIDWORKS 2026 SP05.2"
install/wpf-fixes.sh      # eDrawings: a missing WPF theme assembly, and a black window
```

File Utilities is not a program: it is the Windows Explorer right-click tool for renaming and moving SOLIDWORKS files with their references, plus the Document Manager library. It goes into `Common Files\SOLIDWORKS Shared`.

## 6. Optional: drive the pages from a terminal

Everything above can be done with the mouse. To check or drive the Installation Manager from a terminal instead (it worked unattended in the tested install), start it with WebView2's DevTools port:

```bash
SW_WV2_EXTRA=--remote-debugging-port=9222 bin/sw-wine wine 'C:\swdist\SOLIDWORKS_2026_sp05.2\sldim\sldIM.exe'
tools/sim-cdp.py text                       # what the page says
tools/sim-cdp.py eval 'OnHTML_BUTTON(5002)' # Next
tools/sim-cdp.py serial                     # fill the serial boxes (hidden prompt or SW_SERIAL)
```

`tools/sim-cdp.py` lists the page functions behind each button. Two rules:

- Wait until the page has been rebuilt once (step 2) before you connect. Talking to it earlier made the rebuild fail.
- Pass the same `SW_WV2_EXTRA` to **every** `sw-wine` command while the Installation Manager is open. The wrapper rewrites WebView2's argument policy on each run, and a later WebView2 window with different arguments than the running browser fails to open.

## 7. Launchers

```bash
install/fix-desktop-entries.sh
```

Wine created icons and menu entries that start plain `wine`. It also puts `.lnk` files on the Linux desktop; they do nothing there and can go. The `.sldprt` file associations stay with whichever install had them first.

## 8. First start and activation

```bash
bin/sw-wine wine 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe'
```

The **SOLIDWORKS Product Activation** wizard opens before the main window (there is a 30-day grace period if you choose later). Choose to activate now, **Automatically over the Internet**, enter your e-mail address, **Next**. The tested install answered "Activation/Reactivation Succeeded" and listed the products with their expiry date. Then come the licence agreement and the default units and dimension standard for the templates.

Before you replace or wipe the prefix, deactivate the licence in SOLIDWORKS (**Help > Licenses > Deactivate**), as on Windows. Otherwise the activation stays tied to this prefix and the reseller has to reset it.
