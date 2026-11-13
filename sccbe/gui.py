"""The desktop app: one window with the top bar, and every part of SCC
Broadcast Engine running inside it.

    SCCBroadcastEngine.exe          the built app
    python SCCBroadcastEngine.py    the same, from source (pip install pywebview)

    --debug        right-click > Inspect in the window
    --no-window    run without a window (the pages are at http://127.0.0.1:8770/)
"""

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.request
import webbrowser

TITLE = "SCC Broadcast Engine"


def message_box(text, title=TITLE, error=False):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10 if error else 0x40)
    else:
        print(f"{title}: {text}")


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            return json.loads(r.read()).get("app", {}).get("name") == TITLE
    except Exception:
        return False


class Windows:
    """The app's windows (pywebview): the main one, and the ones parts open
    (Multistream's chat). The HUD-over-the-game windows open themselves."""

    def __init__(self, shell):
        self.shell = shell
        self.main = None
        self.extra = []

    def chat_window(self, url):
        import webview
        w = webview.create_window("SCC Multistream chat", url, width=420, height=760, background_color="#08120c")
        self.extra.append(w)
        return w

    def close(self):
        """Closes the app (an update is about to restart it)."""
        if self.main is not None:
            self.main.destroy()

    def on_main_closed(self):
        # Closing the main window closes the app: the HUD-over-the-game
        # windows and any chat windows go with it.
        for part in self.shell.parts:
            ow = getattr(part.app, "overlay_window", None) if part.app is not None else None
            if ow is not None:
                try:
                    ow.close()
                except Exception:
                    pass
        for w in self.extra:
            try:
                w.destroy()
            except Exception:
                pass


def smoke_test(shell, port, out_dir):
    """Used by the build: start every part and check each serves its pages and
    the libraries it needs are in the build. Writes smoke-test.txt to out_dir."""
    results, ok = [], True
    for part in shell.parts:
        part.start(None)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and any(p.status == "starting" for p in shell.parts):
        time.sleep(0.25)
    checks = [("shell", port, ["/", "/api/state", "/app.js", "/app.css"])]
    pages = {"engine": ["/control", "/output", "/api/state"], "lol": ["/start", "/control", "/overlay"],
             "val": ["/start", "/control", "/overlay"], "cod": ["/control", "/overlay"], "rl": ["/start", "/control", "/overlay"],
             "smash": ["/control", "/overlay"], "ow": ["/control", "/overlay"], "builder": ["/"], "stream": ["/"]}
    for part in shell.parts:
        if part.status != "on":
            ok = False
            results.append(f"FAIL {part.title} didn't start: {part.status} {part.error}")
            continue
        results.append(f"OK   {part.title} running on {part.port}")
        checks.append((part.title, part.port, pages.get(part.key, ["/"])))
    for name, p, paths in checks:
        for path in paths:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{p}{path}", timeout=8) as r:
                    results.append(f"OK   {name} {path} ({len(r.read())} bytes)")
            except Exception as e:
                ok = False
                results.append(f"FAIL {name} {path}: {e}")
    libs = ["webview", "PIL", "psd_tools", "zstandard", "openpyxl", "numpy", "cv2", "cryptography", "imageio_ffmpeg"]
    if sys.platform == "win32":
        libs += ["webview.platforms.winforms", "winrt.windows.media.ocr", "dxcam"]
    for lib in libs:
        try:
            __import__(lib)
            results.append(f"OK   library {lib}")
        except Exception as e:
            ok = False
            results.append(f"FAIL library {lib}: {e!r}")
    try:
        from multistream.config import tool
        from .config import FROZEN
        for t in ("mediamtx", "ffmpeg"):
            path = tool(t)
            found = bool(path and os.path.isfile(path))
            if not found and FROZEN:
                ok = False   # the release must carry them
            results.append(f"{'OK  ' if found else 'FAIL' if FROZEN else 'WARN'} {t}: {path}")
    except Exception as e:
        results.append(f"WARN multistream tools: {e!r}")
    with open(os.path.join(out_dir, "smoke-test.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(results + ["PASSED" if ok else "FAILED"]) + "\n")
    return ok


def main(argv=None):
    # A windowed .exe has no console; give print() somewhere harmless to go.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    parser = argparse.ArgumentParser(description=f"{TITLE} desktop app")
    parser.add_argument("--port", type=int, help="the app's own pages (default 8770)")
    parser.add_argument("--debug", action="store_true", help="allow right-click > Inspect in the window")
    parser.add_argument("--no-window", action="store_true", help="run without a window")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.smoke_test:
        # Its own data folder, so the test leaves nothing in the download.
        os.environ["SCCBE_DATA"] = tempfile.mkdtemp(prefix="sccbe-smoke-")
    from . import config
    if not os.environ.get("SCCBE_DATA"):
        os.environ["SCCBE_DATA"] = config.DATA_DIR
    config.DATA_DIR = os.environ["SCCBE_DATA"]
    os.makedirs(config.DATA_DIR, exist_ok=True)
    from . import parts as P
    P.add_to_path()
    from .log import log, open_file
    open_file(os.path.join(config.DATA_DIR, "shell"))
    from .app import Shell, start

    shell = Shell(config.Settings(os.path.join(config.DATA_DIR, "shell", "settings.json")))
    port = args.port or shell.settings.get()["http_port"]
    own = True
    try:
        start(shell, port)
    except OSError as e:
        if already_running(port):
            own = False   # already open: just open another window onto it
        else:
            message_box(f"Couldn't start on port {port}:\n{e}\n\nAnother program may be using that port.", error=True)
            return 1

    if args.smoke_test:
        ok = smoke_test(shell, port, config.APP_DIR)
        shell.stop()
        return 0 if ok else 1

    url = f"http://127.0.0.1:{port}/"
    if args.no_window:
        shell.start_parts()
        log(f"Running without a window: {url}  (Ctrl+C stops)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        shell.stop()
        return 0

    try:
        import webview
        for key in ("ALLOW_DOWNLOADS", "IGNORE_SSL_ERRORS"):
            # Downloads: exports and backups. SSL: the Observer Client shows the
            # GFX PC's HUD over https, with the certificate that PC made for itself.
            try:
                webview.settings[key] = True
            except Exception:
                pass
        windows = Windows(shell)
        windows.main = webview.create_window(f"{TITLE} {shell.updater.current}", url, width=1600, height=940,
                                             min_size=(1100, 680), background_color="#0c0c0e", text_select=True)
        windows.main.events.closed += windows.on_main_closed
        if own:
            shell.windows = windows
            shell.updater.on_exit = windows.close
            shell.start_parts()
        webview.start(debug=args.debug)
    except Exception as e:
        # No WebView2 (very old Windows 10) or no window library: use the browser.
        log(f"Couldn't open the app window ({e!r}); using the web browser instead", "warn")
        if own:
            shell.start_parts()
        webbrowser.open(url)
        if own:
            message_box(f"{TITLE} has opened in your web browser.\n\nIt keeps running until you close this box.")
    finally:
        if own:
            shell.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
