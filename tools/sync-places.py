#!/usr/bin/env python3
"""Write a .reg file that puts the Linux places into Wine's file dialogs.

usage: sync-places.py OUT.reg

Places are the file manager's local bookmarks -- KDE's
~/.local/share/user-places.xbel (Home, Desktop, Documents, Downloads, ...), or
else Home, the XDG user folders and GTK bookmarks (~/.config/gtk-3.0/bookmarks)
-- then the lines of ~/.config/sw-wine/places ("Title=/path", for folders you
want there too), then File System (/). Each becomes a desktop
namespace item served by swplaces.dll, so it shows in the left pane of the
Vista-style Open/Save dialog (SOLIDWORKS' File > Open) and in the "Look in"
list of the old one; the first five of PLACES_BAR also fill the old dialog's
places bar. Wine's own My Documents, Trash and "/" items are hidden, since
Documents and File System replace them.

Items use CLSIDs {5E1F00nn-...} in list order (Wine lists namespace keys
sorted by name); stale ones from a longer earlier list are deleted.
"""
import os, sys, xml.etree.ElementTree as ET
from urllib.parse import urlparse, unquote

HOME = os.path.expanduser('~')
XBEL = os.path.join(HOME, '.local/share/user-places.xbel')
GTK_BOOKMARKS = os.path.join(HOME, '.config/gtk-3.0/bookmarks')
EXTRA_FILE = os.path.join(HOME, '.config/sw-wine/places')
PLACES_BAR = ['Home', 'Desktop', 'Documents', 'Downloads']   # then the first extra place
ICONS = {'Desktop': -35, 'File System': -9}          # shell32.dll icon ids; default folder (-4)
MAX_PLACES = 64
GUID = '{5E1F00%02X-0C1D-4A5B-8C7D-53574C494E58}'
DLL = r'C:\windows\system32\swplaces.dll'
HKCR = r'HKEY_LOCAL_MACHINE\Software\Classes\CLSID'
NAMESPACE = r'HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\Desktop\NameSpace'
PLACESBAR = r'HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Policies\Comdlg32\Placesbar'
# Wine's own desktop items: (CLSID, ShellFolder values to keep) -- hidden with SFGAO_NONENUMERATED
WINE_ITEMS = {'{450D8FBA-AD25-11D0-98A8-0800361B1103}': (0xb0000000, True),   # My Documents
              '{645FF040-5081-101B-9F08-00AA002F954E}': (0x20000140, False),  # Trash
              '{9D20AAE8-0625-44B0-9CA7-71889C2254D9}': (0xb0000000, True)}   # "/"
SFGAO_NONENUMERATED = 0x00100000


def xdg_places():
    """Home, the XDG user folders and GTK bookmarks (GNOME and others)."""
    out = [('Home', HOME)]
    dirs = {}
    try:
        for line in open(os.path.join(HOME, '.config/user-dirs.dirs')):
            if line.startswith('XDG_') and '=' in line:
                k, v = line.strip().split('=', 1)
                dirs[k] = os.path.expandvars(v.strip('"'))
    except OSError:
        pass
    for key, title in [('XDG_DESKTOP_DIR', 'Desktop'), ('XDG_DOCUMENTS_DIR', 'Documents'),
                       ('XDG_DOWNLOAD_DIR', 'Downloads'), ('XDG_MUSIC_DIR', 'Music'),
                       ('XDG_PICTURES_DIR', 'Pictures'), ('XDG_VIDEOS_DIR', 'Videos')]:
        path = dirs.get(key, os.path.join(HOME, title))
        if os.path.normpath(path) != HOME:
            out.append((os.path.basename(path.rstrip('/')) or title, path))
    try:
        for line in open(GTK_BOOKMARKS):
            uri, _, name = line.strip().partition(' ')
            url = urlparse(uri)
            if url.scheme == 'file':
                path = unquote(url.path)
                out.append((name or os.path.basename(path.rstrip('/')) or '/', path))
    except OSError:
        pass
    return out


def extra_places():
    out = []
    try:
        for line in open(EXTRA_FILE):
            title, sep, path = line.strip().partition('=')
            if sep and title.strip() and not title.startswith('#'):
                out.append((title.strip(), os.path.expanduser(path.strip())))
    except OSError:
        pass
    return out


def dolphin_places():
    try:
        root = ET.parse(XBEL).getroot()
    except (OSError, ET.ParseError):
        return xdg_places()
    out = []
    for bm in root.iter('bookmark'):
        url = urlparse(bm.get('href', ''))
        if url.scheme != 'file':
            continue
        if any((e.tag.endswith('IsHidden') and (e.text or '').strip() == 'true') for e in bm.iter()):
            continue
        title = (bm.findtext('title') or '').strip() or os.path.basename(unquote(url.path)) or '/'
        out.append((title, unquote(url.path)))
    return out


def winpath(path):
    return 'Z:' + path.replace('/', '\\') if path != '/' else 'Z:\\'


def q(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def main(out):
    places, seen = [], set()
    extras = extra_places()
    for title, path in dolphin_places() + extras + [('File System', '/')]:
        path = os.path.normpath(path)
        if path in seen or not os.path.isdir(path):
            continue
        seen.add(path)
        places.append((title, path))
    places = places[:MAX_PLACES]

    lines = ['Windows Registry Editor Version 5.00', '']
    for i in range(MAX_PLACES):                      # clear everything we may have written before
        lines += ['[-%s\\%s]' % (HKCR, GUID % i), '[-%s\\%s]' % (NAMESPACE, GUID % i)]
    lines += ['[-%s]' % PLACESBAR, '']
    for i, (title, path) in enumerate(places):
        g, key = GUID % i, HKCR + '\\' + GUID % i
        lines += ['[%s]' % key, '@=' + q(title), '',
                  '[%s\\DefaultIcon]' % key, '@=' + q(r'C:\windows\system32\shell32.dll,%d' % ICONS.get(title, -4)), '',
                  '[%s\\InprocServer32]' % key, '@=' + q(DLL), '"ThreadingModel"="Both"', '',
                  '[%s\\Instance]' % key, '"CLSID"="{0AFACED1-E828-11D1-9187-B532F1E9575D}"', '',
                  '[%s\\Instance\\InitPropertyBag]' % key, '"Target"=' + q(winpath(path)), '',
                  '[%s\\ShellFolder]' % key, '"Attributes"=dword:f0000000', '"WantsFORPARSING"=""', '',
                  '[%s\\%s]' % (NAMESPACE, g), '@=' + q(title), '']
    for clsid, (attrs, parsing) in WINE_ITEMS.items():
        lines += ['[%s\\%s\\ShellFolder]' % (HKCR, clsid), '"Attributes"=dword:%08x' % (attrs | SFGAO_NONENUMERATED)]
        lines += (['"CallForAttributes"=dword:40000000', '"WantsFORPARSING"=""'] if parsing else []) + ['']
    by_title = {t: GUID % i for i, (t, _) in enumerate(places)}
    bar = [by_title[t] for t in PLACES_BAR + [t for t, _ in extras[:1]] if t in by_title]
    bar += [GUID % i for i in range(len(places)) if GUID % i not in bar]
    lines += ['[%s]' % PLACESBAR] + ['"Place%d"="::%s"' % (n, g) for n, g in enumerate(bar[:5])] + ['']
    with open(out, 'w', encoding='utf-16') as f:     # UTF-16 with BOM, as regedit expects for v5 files
        f.write('\r\n'.join(lines) + '\r\n')
    for title, path in places:
        print('%-12s %s' % (title, winpath(path)))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
