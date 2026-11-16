"""Backups of the data folder, made before anything changes it on its own:
the first start of a new version (each part may upgrade its files then)
and every import of the old apps' data.

    data/_backups/<date>-<why>/<part>/...     a copy of data/ as it was
    data/_backups/<date>-<why>/README.txt     what it is, how to put it back
    data/_backups/last-version.txt            the version that last started

Big files (videos over BIG bytes) are left out: they're listed in the README
and are never changed by an update. The newest KEEP backups are kept.
"""

import os
import re
import shutil
import time

from .log import log

FOLDER = "_backups"
KEEP = 10
BIG = 50 * 1024 * 1024
SKIP_DIRS = {FOLDER, "parts", "_update", "frames", "__pycache__"}


def backups_dir(data_dir):
    return os.path.join(data_dir, FOLDER)


def _has_data(data_dir):
    try:
        return any(n != FOLDER for n in os.listdir(data_dir))
    except OSError:
        return False


def make(data_dir, why):
    """Copies data_dir into _backups/<date>-<why>. Returns the folder (None
    when there's nothing to back up)."""
    if not _has_data(data_dir):
        return None
    why = re.sub(r"[^A-Za-z0-9.]+", "-", why).strip("-")[:40] or "backup"
    stamp = time.strftime("%Y-%m-%d_%H%M%S")
    dest = os.path.join(backups_dir(data_dir), f"{stamp}-{why}")
    n = 2
    while os.path.exists(dest):
        dest, n = os.path.join(backups_dir(data_dir), f"{stamp}-{why}-{n}"), n + 1
    skipped, count = [], 0
    for root, dirs, files in os.walk(data_dir):
        rel_root = os.path.relpath(root, data_dir)
        dirs[:] = [d for d in dirs if not (rel_root == "." and d in SKIP_DIRS) and d != "__pycache__"]
        for f in files:
            src = os.path.join(root, f)
            rel = os.path.normpath(os.path.join(rel_root, f))
            if f.endswith((".tmp", ".log")):
                continue
            try:
                if os.path.getsize(src) > BIG:
                    skipped.append(rel)
                    continue
                os.makedirs(os.path.join(dest, os.path.dirname(rel)), exist_ok=True)
                shutil.copy2(src, os.path.join(dest, rel))
                count += 1
            except OSError as e:
                skipped.append(f"{rel} ({e})")
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "README.txt"), "w", encoding="utf-8") as f:
        f.write(f"SCC Broadcast Engine data, backed up {time.strftime('%Y-%m-%d %H:%M:%S')} ({why}).\n\n"
                "To put it back: close SCC Broadcast Engine, then copy the folders in here\n"
                f"(gfxengine, shell, ...) over the ones in {data_dir}.\n")
        if skipped:
            f.write("\nNot copied (big video files, never changed by updates):\n" + "\n".join(skipped) + "\n")
    log(f"Backed up the data folder ({count} files) to {dest}")
    _trim(data_dir)
    return dest


def _trim(data_dir):
    root = backups_dir(data_dir)
    old = sorted((d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))),
                 key=lambda d: os.path.getmtime(os.path.join(root, d)))
    for d in old[:-KEEP]:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)


def on_start(data_dir, version):
    """A backup when this is the first start of another version than last time."""
    marker = os.path.join(backups_dir(data_dir), "last-version.txt")
    try:
        with open(marker, encoding="utf-8") as f:
            last = f.read().strip()
    except OSError:
        last = ""
    if last == version:
        return None
    dest = make(data_dir, f"before-{version}" + (f"-from-{last}" if last else ""))
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w", encoding="utf-8") as f:
        f.write(version)
    return dest


def listing(data_dir):
    root = backups_dir(data_dir)
    try:
        names = sorted((d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))), reverse=True)
    except OSError:
        names = []
    return {"folder": root, "backups": names}
