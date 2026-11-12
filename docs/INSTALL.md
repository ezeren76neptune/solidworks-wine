# Installing SOLIDWORKS for Makers under Wine

This walkthrough follows the one install that works (see the status note in the [README](../README.md)). Allow an afternoon for it.

Every Wine command for this prefix goes through `bin/sw-wine`. That includes `wine`, `winetricks`, `regedit` and `wineserver -k`. Starting anything in the prefix with plain `wine` skips the fixes, and it can also start a wineserver that sees `/dev/ntsync`, which then breaks later commands. The scripts below use the wrapper for you.

The commands assume the repository is cloned to `~/solidworks-wine`, so the prefix is `~/solidworks-wine/prefix`. To use a different prefix, set `WINEPREFIX` for every command.

## 0. Packages

On Fedora:

```bash
sudo dnf install wine winetricks bubblewrap gcc binutils python3 curl unzip p7zip-plugins cabextract
```

Other distributions need the same set. Wine must be 11.x. The tested build was Wine 11.20 Staging.

Then compile the Wine additions:

```bash
cd ~/solidworks-wine
tools/build.sh
```

## 1. The Wine prefix

```bash
install/setup-prefix.sh
```

This takes about 5 minutes and downloads .NET Framework 4.8, the core fonts and MSXML 6 from Microsoft through winetricks. It also sets:

- Windows 11 as the reported version, because the installer refuses Windows 10;
- the .NET release number that the installer checks for;
- native Visual C++ runtimes;
- GLX instead of EGL;
- no crash dialogs;
- a compatibility setting for WebView2.

Each setting is explained in a comment in the script.

## 2. Get the installer media and WebView2

You need two things from Dassault and one from Microsoft. None of them can be redistributed, so they are not in this repository.

### a. The SOLIDWORKS "bootstrap" media

This is a zip of about 26 MB named like `SOLIDWORKS_3DEXP_Desktop.Full-CP0490V6R2026x.HF5.9.Windows64.zip`.

- **Tested way:** install SOLIDWORKS once from the 3DEXPERIENCE platform on any Windows PC or VM. The 3DEXPERIENCE Launcher keeps the zip under
  `C:\ProgramData\DassaultSystemes\3DEXPERIENCELauncher\defaultDataStore\Media\<date>\win_b64\CODE\`. Copy it over. The installer command line in that launcher's logs also holds the values for step 4.
- **Untested way, no Windows needed:** the 3DEXPERIENCE Launcher MSI does install and run under Wine. Its service answers on `127.0.0.1:20250`. In principle you can install the Launcher into this prefix (`bin/sw-wine wine msiexec /i 3DEXPERIENCELauncher.msi`), sign in to the 3DEXPERIENCE platform in a Linux browser and press **Install** on SOLIDWORKS, so the Launcher downloads the media into the prefix's `defaultDataStore\Media`. Nobody has tried this end to end yet.

The archive list in `install/` matches the HF5.9 media. With other media, see step 3.

### b. The WebView2 runtime

It shows the 3DEXPERIENCE sign-in page.

- **Tested way:** copy the folder `C:\Program Files (x86)\Microsoft\EdgeWebView\Application\<version>` from a Windows PC.
- **Untested but equivalent:** the x64 "Fixed Version" runtime `.cab` from Microsoft's WebView2 download page.

Either way:

```bash
install/install-webview2.sh /path/to/157.0.4341.42                         # a copied folder
install/install-webview2.sh Microsoft.WebView2.FixedVersionRuntime.<ver>.x64.cab
```

The script copies the runtime to the place the SOLIDWORKS loader looks in and writes the `EdgeUpdate\Clients` and `EdgeUpdate\ClientState` (`EBWebView`) registry values it needs.

## 3. Stage the media and the installer archives

```bash
install/stage-media.sh SOLIDWORKS_3DEXP_Desktop.Full-CP0490V6R2026x.HF5.9.Windows64.zip
install/download-cafs.sh
```

`stage-media.sh` unpacks the media to `C:\DSInstall`. It then patches one byte in each of the installer stubs: they check for an "Internet Explorer 10" export (`wininet!HttpWebSocketReceive`) that Wine lacks.

`download-cafs.sh` downloads the 181 component archives (CAFs, about 7 GB) for this media from Dassault's public download bucket. It saves them into the installer's archive folder. It resumes and skips files that are already complete.

With different media, the archive list differs. Make one from the `.dsa` files in a Windows install's `C:\ProgramData\DassaultSystemes\3DEXPERIENCELauncher\defaultDataStore\Cafs` folder. The installer may also download missing archives itself, because the answer file names the download location, but that is untested under Wine.

## 4. The installer's answer file

```bash
install/make-install-json.py --tenant OI000123456
```

The tenant is your 3DEXPERIENCE platform ID. It is the first part of the platform's web address: `https://oi000123456-us1-makers-space.3dexperience.3ds.com/…` gives `OI000123456`.

- If your address shows another region than `us1`, add `--region eu1`, for example.
- The Makers registry and sign-in service were in `eu1` for the tested account. Change that with `--registry-region`.
- If you copied the media from Windows, compare the values with the installer command line in the Launcher's logs.

The file goes to `C:\DSInstall\sw-install.json`. It has to be a JSON list, and the script writes it that way.

## 5. Run Dassault's installer (first pass)

```bash
install/run-installer.sh
```

The installer's own window appears. Click through its panels. In the tested install, it installed the 3DEXPERIENCE platform part, the Visual C++ prerequisites, CEF and the SOLIDWORKS Login Manager. It then failed on the SOLIDWORKS MSI, which is expected: Wine's MSI cannot install it unmodified.

The installer leaves the MSIs in `…\SOLIDWORKS 3DEXPERIENCE R2026x\win_b64\resources\MSI\`. Its logs are under `InstallData\log` in the same folder.

## 6. Fix and install the SOLIDWORKS and Visualize MSIs

```bash
install/build-msi-tools.sh    # msisql/msifeat, compiled with the prefix's own C# compiler
install/patch-msis.sh
install/install-msis.sh
```

`patch-msis.sh` edits the MSI databases in place:

- It turns off `InstallSpatialIOP`, which unzips through a Windows shell API that Wine lacks, and unpacks `spatialiop.zip` with 7z instead.
- It makes the `SWRegistration` step continue on error. A few shell-extension registrations fail under Wine and would roll the whole install back.
- It clears the "follow parent" flag on the help, manual and example features that Windows leaves out.

`install-msis.sh` runs `msiexec` with the full list of features a Windows install ends up with (`install/solidworks-addlocal.txt`). Wine's MSI does not add the parent features of the ones the Dassault installer asks for, so it would otherwise install almost nothing. Expect several minutes. `msiexec-exit=0` means success. The logs are in `C:\swtools`.

## 7. Run the installer again

```bash
install/run-installer.sh
```

This time it finds SOLIDWORKS installed and goes on with the rest, including the hotfixes, the connectors and the dictionary compile. That last step needs the `ntdll` addition the wrapper provides. In the tested install, this pass needed no clicks.

If it stops on another MSI, the `report.xml` in `C:\DSInstall` and the installer log name it. Running `patch-msis.sh` again does no harm.

## 8. Launchers

```bash
install/fix-desktop-entries.sh
```

Wine creates a "SOLIDWORKS Design" desktop icon, app-menu entries and `.sldprt`/`.sldasm`/`.slddrw` file associations, all using plain `wine`. This script repoints them at the wrapper. After that, double-clicking a part in your file manager opens it in SOLIDWORKS.

## 9. First start

```bash
bin/sw-wine wine 'C:\users\Public\Desktop\SOLIDWORKS Design.lnk'
```

1. The 3DEXPERIENCE sign-in page opens in a WebView2 window. Sign in yourself. If you see a plain grey Wine "username/password" box instead, WebView2 is missing: close the box without typing your password and redo step 2b.
2. SOLIDWORKS shows "Loading registry…" and then the main window. The sign-in is remembered for later starts.
3. Go to **Tools > Options > System Options > Performance** and turn **off** "Enhanced graphics performance". With it on, the 3D view stays black.
4. Leave with **File > Exit**, so the setting is saved, and start SOLIDWORKS again.

To stop everything in the prefix:

```bash
bin/sw-wine wineserver -k
```

Never use `wineserver -w` once SOLIDWORKS has run: the Launcher service never exits, so `-w` never returns.

GPU: SOLIDWORKS uses the system's default GPU. `SW_GPU=nvidia bin/sw-wine wine …` forces NVIDIA PRIME offload, but on the tested machine that drew no shaded faces.

## 10. Optional: your Linux folders in the Open dialog

SOLIDWORKS uses Wine's Vista-style Open dialog. By default its left pane lists Wine's own items: My Computer, Trash and "/".

```bash
tools/build-pe.sh    # builds tools/build/swplaces.dll with MinGW inside a Fedora container (podman)
```

On the next start, the wrapper registers your file manager's places in that pane: Home, Desktop, Documents, Downloads, and so on. It reads KDE's places, or else the XDG folders and GTK bookmarks, and adds "File System". It hides Wine's own items. The old-style dialog's places bar gets the first five places.

To add more folders, put lines such as `CAD=~/Documents/CAD` in `~/.config/sw-wine/places`. The wrapper re-registers the list whenever it changes.

## Uninstall

```bash
bin/sw-wine wineserver -k
rm -rf ~/solidworks-wine/prefix ~/solidworks-wine/tools/build
```

Then delete the Wine-made launchers: the SOLIDWORKS `.desktop` files on your desktop, `~/.local/share/applications/wine/Programs/*SOLIDWORKS*` and `~/.local/share/applications/wine-extension-sld*.desktop`.
