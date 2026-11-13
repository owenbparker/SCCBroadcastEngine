"""The app's log: printed, kept for the Settings page and written to
data/shell/log.txt (the last run's, for problem reports)."""

import collections
import os
import threading
import time

_lines = collections.deque(maxlen=500)
_lock = threading.Lock()
_file = None


def open_file(folder):
    global _file
    try:
        os.makedirs(folder, exist_ok=True)
        _file = open(os.path.join(folder, "log.txt"), "w", encoding="utf-8", buffering=1)
    except OSError:
        _file = None


def log(message, level="info"):
    line = {"t": time.strftime("%H:%M:%S"), "level": level, "msg": str(message)}
    text = f"[{line['t']}] {'' if level == 'info' else level.upper() + ': '}{message}"
    with _lock:
        _lines.append(line)
        if _file:
            try:
                _file.write(text + "\n")
            except (OSError, ValueError):
                pass
    try:
        print(text, flush=True)
    except (OSError, ValueError, AttributeError):
        pass


def lines():
    with _lock:
        return list(_lines)
