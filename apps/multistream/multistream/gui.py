"""The desktop app: the control panel in its own window.

    SCCMultistream.exe                 the built app
    python -m multistream.gui          the same, from source (needs: pip install pywebview)
"""

import argparse
import json
import os
import sys
import urllib.request
import webbrowser

from . import selftest
from .app import StreamApp, start, stop
from .config import DATA_DIR, PORT
from .log import log

TITLE = "SCC Multistream"


def message_box(text, title=TITLE, error=False):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10 if error else 0x40)
    else:
        print(f"{title}: {text}")


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            return "relay" in json.loads(r.read())
    except Exception:
        return False


def smoke_test(port):
    """Used by a build: the app serves its page, and the relay works end to
    end on this PC (see selftest.py). Writes smoke-test.txt next to the app;
    True if all went well."""
    results, ok = [], True
    app = StreamApp()
    try:
        start(app, port)
        for path in ("/", "/api/state", "/update.js", "/fonts/Inter.ttf", "/assets/platforms/youtube.png"):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
                    results.append(f"OK   {path} ({len(r.read())} bytes)")
            except Exception as e:
                ok = False
                results.append(f"FAIL {path} ({e})")
        passed, checks = selftest.run()
        ok = ok and passed
        results += [f"{'OK  ' if p else 'FAIL'} {t}" for p, t in checks]
    finally:
        stop(app)
    with open(os.path.join(DATA_DIR, "smoke-test.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(results + ["PASSED" if ok else "FAILED"]) + "\n")
    return ok


def main():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--debug", action="store_true", help="allow right-click > Inspect in the window")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.smoke_test:
        return 0 if smoke_test(args.port) else 1

    url = f"http://127.0.0.1:{args.port}/"
    if already_running(args.port):
        # One relay at a time: open another window onto the one that's running.
        own, app = False, None
    else:
        own, app = True, StreamApp()
        try:
            start(app, args.port)
        except OSError as e:
            message_box(f"Couldn't start on port {args.port}:\n{e}", error=True)
            return 1

    try:
        import webview
        version = app.updater.current if app else ""
        window = webview.create_window(f"{TITLE} {version}".strip(), url, width=1280, height=760,
                                       min_size=(900, 560), background_color="#08120c")
        if app:
            app.updater.on_exit = window.destroy
        webview.start(debug=args.debug)
    except Exception as e:
        log(f"Couldn't open the app window ({e!r}); using the web browser instead", "warn")
        webbrowser.open(url)
        if own:
            message_box("SCC Multistream has opened in your web browser.\n\nIt keeps streaming until you close this box.")
    finally:
        if own:
            stop(app)
    return 0


if __name__ == "__main__":
    sys.exit(main())
