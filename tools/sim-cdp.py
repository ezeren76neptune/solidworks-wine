#!/usr/bin/env python3
"""Read and drive the SOLIDWORKS Installation Manager's pages through WebView2's DevTools port.

The Installation Manager draws its pages in WebView2. Under Wine you can click them, and with
tools/build/autoattach.exe running you can type into them, but this lets you check or drive
each page from a terminal too (see docs/INSTALL-STANDALONE.md). Start the Installation Manager
with SW_WV2_EXTRA=--remote-debugging-port=9222, and wait until its page has been rebuilt once
before connecting.

usage: tools/sim-cdp.py [--port 9222] [--match <url/title part>] list
       tools/sim-cdp.py ... text                  visible text of the page
       tools/sim-cdp.py ... eval '<javascript>'   result printed as JSON
       tools/sim-cdp.py ... shot <file.png>       screenshot of the page
       tools/sim-cdp.py ... serial                fill the SOLIDWORKS serial boxes; the serial is
                                                  read from $SW_SERIAL or a hidden prompt, never printed
Page functions the installer's own buttons call (eval them):
       OnHTML_BUTTON(5002)  Next / Download and Install      OnHTML_BUTTON(5001)  Back
       OnHTML_BUTTON(5003)  Cancel     OnHTML_BUTTON(5004)  Finish     OnHTML_BUTTON(5012)  Back to Summary
       OnHTML_LINK(0)  Summary > Products "Change"    OnHTML_LINK(2)  Download Options "Change"
       OnHTML_CHECKBOX(box, id) after setting box.checked (ids are in the checkBox_<id> element ids)
Plain .click() does nothing: the footer buttons react to mouse-up and Enter only.
Needs the python3 'websockets' package.
"""
import asyncio
import base64
import getpass
import json
import os
import re
import sys
import urllib.request

import websockets


def targets(port):
    with urllib.request.urlopen('http://127.0.0.1:%d/json/list' % port, timeout=5) as r:
        return json.load(r)


async def call(ws_url, method, params=None):
    async with websockets.connect(ws_url, max_size=64 << 20) as ws:
        await ws.send(json.dumps({'id': 1, 'method': method, 'params': params or {}}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get('id') == 1:
                return msg


def evaluate(ws, expr):
    r = asyncio.run(call(ws, 'Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True}))
    res = r.get('result', {})
    if 'exceptionDetails' in res:
        sys.exit('javascript error: %s' % json.dumps(res['exceptionDetails'].get('exception', res['exceptionDetails']))[:2000])
    v = res.get('result', {})
    return v.get('value', v.get('description'))


SERIAL_JS = '''(function(parts){
  for (var i = 0; i < 6; i++) {
    var e = document.getElementById("EDIT" + i);
    if (!e) return "EDIT" + i + " not on this page: open the Serial Number page first";
    e.focus(); e.value = parts[i];
    OnHTML_EDIT(e, i, 99);   /* what the box's key-up handler reports */
    OnHTML_EDIT(e, i, 97);   /* and its blur handler */
  }
  return "serial entered";
})(%s)'''


def main(argv):
    port, match = 9222, None
    while argv and argv[0].startswith('--'):
        if argv[0] == '--port' and len(argv) > 1:
            port, argv = int(argv[1]), argv[2:]
        elif argv[0] == '--match' and len(argv) > 1:
            match, argv = argv[1], argv[2:]
        else:
            sys.exit(__doc__)
    if not argv:
        sys.exit(__doc__)
    ts = targets(port)
    if argv[0] == 'list':
        for t in ts:
            print(t.get('type'), '|', t.get('title'), '|', t.get('url'))
        return
    pages = [t for t in ts if t.get('type') == 'page' and (not match or match in t.get('url', '') or match in t.get('title', ''))]
    if not pages:
        sys.exit('no matching page')
    ws = pages[0]['webSocketDebuggerUrl']
    cmd = argv[0]
    if cmd == 'text':
        print(evaluate(ws, 'document.body ? document.body.innerText : ""'))
    elif cmd == 'eval' and len(argv) > 1:
        print(json.dumps(evaluate(ws, argv[1])))
    elif cmd == 'shot' and len(argv) > 1:
        r = asyncio.run(call(ws, 'Page.captureScreenshot', {'format': 'png'}))
        open(argv[1], 'wb').write(base64.b64decode(r['result']['data']))
        print('saved', argv[1])
    elif cmd == 'serial':
        sn = os.environ.get('SW_SERIAL') or getpass.getpass('SOLIDWORKS serial (hidden): ')
        sn = re.sub(r'[^0-9A-Za-z]', '', sn).upper()
        if len(sn) != 24:
            sys.exit('a SOLIDWORKS serial has 24 letters and digits; got %d' % len(sn))
        print(evaluate(ws, SERIAL_JS % json.dumps([sn[i:i + 4] for i in range(0, 24, 4)])))
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
