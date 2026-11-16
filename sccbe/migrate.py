"""Brings in the data of the apps SCC Broadcast Engine replaced (the GFX
Engine and the game HUDs installed on their own, e.g. C:\\SCC GFX Engine),
and of an SCC Broadcast Engine installed in another folder.

It only ever ADDS: the old folders are read, never changed, and nothing in
this app's data folder is replaced.

    GFX Engine   workspaces/<id>   copied in; one whose id is taken here (and
                                   isn't the same) comes in under a new id
                 library/teams.csv the old teams added to the list (a team
                                   that's already here, same name + game, is kept as it is)
                 library/...       logos, photos, fonts: copied when missing; a
                                   different file with the same name gets a new name
                 settings.json     settings this app doesn't have yet; opens the
                                   workspace the old engine had open
    game HUDs    config.json       settings this app doesn't have yet
                 logos/, ...       files copied when missing

It runs when the app starts (before any part does), once for each old folder
(data/shell/imported.json says which), and again from Settings > Folders.
"""

import filecmp
import json
import os
import re
import shutil
import string
import sys
import time

from .log import log

# part folder (data/<part>) -> the name the app was installed under on its own
OLD_APPS = {
    "gfxengine": "SCC GFX Engine",
    "lolhud": "SCC LoL HUD",
    "valhud": "SCC VAL HUD",
    "codhud": "SCC CoD HUD",
    "rlhud": "SCC RL HUD",
    "smashhud": "SCC Smash HUD",
    "owhud": "SCC Overwatch HUD",
    "multistream": "SCC Multistream",
}
SCCBE_NAME = "SCC Broadcast Engine"

# Never copied: the program itself, its updates, and things made again on their own.
SKIP_DIRS = {"_internal", "_update", "_backup", "certs", "frames", "__pycache__", "data"}
SKIP_FILES = re.compile(r"(?i)(\.(exe|dll|pyd|log|tmp|lock)$|^unins\d*\.|^smoke-test\.txt$)")
SETTINGS_FILES = ("settings.json", "config.json")
MARK = "imported.json"


# --- finding the old folders -----------------------------------------------------

def _registry_folders(name):
    """Where Windows says an app called name (or name + version) is installed."""
    if sys.platform != "win32":
        return []
    import winreg
    out = []
    keys = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in keys:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        shown = str(winreg.QueryValueEx(k, "DisplayName")[0])
                        if not shown.lower().startswith(name.lower()):
                            continue
                        for value in ("InstallLocation", "Inno Setup: App Path"):
                            try:
                                out.append(str(winreg.QueryValueEx(k, value)[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
    return out


def _guesses(name):
    """The usual places an app called name was installed."""
    out = []
    if sys.platform == "win32":
        out += [f"{d}:\\{name}" for d in string.ascii_uppercase if os.path.isdir(f"{d}:\\")]
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(env)
            if base:
                out += [os.path.join(base, name), os.path.join(base, "Programs", name)]
        home = os.path.expanduser("~")
        out += [os.path.join(home, where, name) for where in ("Desktop", "Documents", "Downloads")]
    return out


def _norm(path):
    return os.path.normcase(os.path.abspath(path.rstrip("\\/"))) if path else ""


def _has_data(part, folder):
    if not os.path.isdir(folder):
        return False
    if part == "gfxengine":
        return any(os.path.exists(os.path.join(folder, n)) for n in ("workspaces", "workspace", "library", "settings.json"))
    return any(os.path.exists(os.path.join(folder, n)) for n in SETTINGS_FILES + ("logos", "profiles", "huds"))


def find_sources(data_dir, extra=()):
    """[(part, old folder)] for every old app found with data in it.
    extra: folders to look in as well (an old app's install folder, an old
    SCC Broadcast Engine's install or data folder)."""
    here = _norm(data_dir)
    found, seen = [], set()

    def add(part, folder):
        n = _norm(folder)
        if not n or n in seen or n == here or n.startswith(here + os.sep) or not _has_data(part, folder):
            return
        seen.add(n)
        found.append((part, folder))

    for part, name in OLD_APPS.items():
        for folder in _registry_folders(name) + _guesses(name):
            add(part, folder)
    sccbe = _registry_folders(SCCBE_NAME) + _guesses(SCCBE_NAME)
    for folder in sccbe:
        for part in OLD_APPS:
            add(part, os.path.join(folder, "data", part))
    for folder in extra or ():
        folder = (folder or "").strip().strip('"')
        if not folder:
            continue
        for base in (folder, os.path.join(folder, "data")):
            for part in OLD_APPS:
                add(part, os.path.join(base, part))
        for part, name in OLD_APPS.items():
            if os.path.basename(folder.rstrip("\\/")).lower() == name.lower():
                add(part, folder)
        add("gfxengine", folder)   # a GFX Engine folder under another name
    return found


# --- copying ---------------------------------------------------------------------

def _files(folder):
    """Every file under folder worth bringing over (paths relative to it)."""
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not SKIP_FILES.search(f):
                yield os.path.relpath(os.path.join(root, f), folder)


def _free_name(path):
    stem, ext = os.path.splitext(path)
    n = 1
    while True:
        p = f"{stem}-old{'' if n == 1 else n}{ext}"
        if not os.path.exists(p):
            return p
        n += 1


def _same_old(src, path):
    """The <name>-old<n> copy of path that is the same as src, if there is one."""
    stem, ext = os.path.splitext(path)
    for n in range(1, 100):
        p = f"{stem}-old{'' if n == 1 else n}{ext}"
        if not os.path.exists(p):
            return None
        if filecmp.cmp(src, p, shallow=False):
            return p
    return None


def _copy_missing(src, dest, report, rename=False, skip=()):
    """Copies the files of src that dest hasn't got. A different file with
    the same name: left alone, or (rename) copied under a new name.
    Returns {old relative path: new relative path} for the renamed ones."""
    renamed = {}
    for rel in _files(src):
        if rel.replace("\\", "/") in skip:
            continue
        s, d = os.path.join(src, rel), os.path.join(dest, rel)
        if os.path.exists(d):
            if not rename or filecmp.cmp(s, d, shallow=False):
                continue
            same = _same_old(s, d)
            if same:    # brought in under a new name before
                renamed[rel.replace("\\", "/")] = os.path.relpath(same, dest).replace("\\", "/")
                continue
            d = _free_name(d)
            renamed[rel.replace("\\", "/")] = os.path.relpath(d, dest).replace("\\", "/")
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        report["files"] += 1
    return renamed


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _merge_settings(src, dest, report, keep=()):
    """Settings the old file has and this app's hasn't (nothing replaced)."""
    old = _read_json(src)
    if not old:
        return {}
    if not os.path.exists(dest):
        _write_json(dest, {k: v for k, v in old.items() if k not in keep})
        report["settings"] += 1
        return old
    new = _read_json(dest)
    added = {k: v for k, v in old.items()
             if k not in keep and (k not in new or new[k] in ("", None, [], {}))
             and v not in ("", None, [], {})}
    if added:
        new.update(added)
        _write_json(dest, new)
        report["settings"] += 1
    return old


# --- the GFX Engine ------------------------------------------------------------------

def _import_workspaces(src, dest, done, report):
    """Old workspaces copied in. done: {old id: id here} from earlier imports
    (updated). Returns the same mapping."""
    os.makedirs(dest, exist_ok=True)
    folders = []
    ws_root = os.path.join(src, "workspaces")
    if os.path.isdir(ws_root):
        folders += [(w, os.path.join(ws_root, w)) for w in sorted(os.listdir(ws_root))]
    legacy = os.path.join(src, "workspace")   # GFX Engine v1.0.1: one workspace
    if os.path.isfile(os.path.join(legacy, "project.json")):
        folders.append(("workspace", legacy))
    for wid, folder in folders:
        pj = os.path.join(folder, "project.json")
        if not os.path.isfile(pj):
            continue
        if wid in done and os.path.isfile(os.path.join(dest, done[wid], "project.json")):
            continue    # brought in before
        here = os.path.join(dest, wid)
        if os.path.isfile(os.path.join(here, "project.json")) and filecmp.cmp(pj, os.path.join(here, "project.json"), shallow=False):
            done[wid] = wid
            continue    # the same workspace is already here
        new_id, n = wid, 2
        while os.path.exists(os.path.join(dest, new_id)):
            new_id, n = f"{wid}-{n}", n + 1
        shutil.copytree(folder, os.path.join(dest, new_id),
                        ignore=shutil.ignore_patterns("*.tmp"))
        if new_id != wid:
            # Same name as one here: say which is which on the home screen.
            data = _read_json(os.path.join(dest, new_id, "project.json"))
            if data:
                data["name"] = f"{data.get('name') or wid} (old GFX Engine)"
                with open(os.path.join(dest, new_id, "project.json"), "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=1)
        done[wid] = new_id
        report["workspaces"].append(new_id)
        log(f"Import: workspace {wid} from {folder} -> {new_id}")
    return done


def _import_teams(src_lib, dest_lib, renamed, report):
    """The old team list added to this one: teams here are kept as they are."""
    if not os.path.isfile(os.path.join(src_lib, "teams.csv")):
        return
    from gfxengine.teams import Teams, key
    old = Teams(src_lib).list()
    if not old:
        return
    mine = Teams(dest_lib)
    current = mine.list()
    have = {key(t) for t in current}
    fix = lambda p: renamed.get(p[len("library/"):], p[len("library/"):]) if p.startswith("library/") else p
    added = []
    for t in old:
        if key(t) in have:
            continue
        have.add(key(t))
        if t.get("logo"):
            t["logo"] = "library/" + fix(t["logo"]) if t["logo"].startswith("library/") else t["logo"]
        for p in t.get("players") or []:
            if p.get("photo", "").startswith("library/"):
                p["photo"] = "library/" + fix(p["photo"])
        added.append(t)
    if not added:
        return
    if os.path.isfile(mine.path):
        shutil.copy2(mine.path, mine.path + f".before-import-{time.strftime('%Y%m%d-%H%M%S')}")
    mine.save(current + added)
    report["teams"] += len(added)
    log(f"Import: {len(added)} teams from {src_lib}")


def _import_engine(src, dest, mark, report):
    done = mark.setdefault("workspaces", {})
    _import_workspaces(src, os.path.join(dest, "workspaces"), done, report)
    src_lib, dest_lib = os.path.join(src, "library"), os.path.join(dest, "library")
    if os.path.isdir(src_lib):
        renamed = _copy_missing(src_lib, dest_lib, report, rename=True, skip={"teams.csv"})
        _import_teams(src_lib, dest_lib, renamed, report)
    # Settings: the engine's own ID stays this app's (the HUDs here pair with it).
    old = _merge_settings(os.path.join(src, "settings.json"), os.path.join(dest, "settings.json"), report,
                          keep=("engine_id", "engine_id_pc", "http_port", "workspace"))
    open_ws = done.get(old.get("workspace")) if old else None
    if report["workspaces"] and open_ws and os.path.isdir(os.path.join(dest, "workspaces", open_ws)):
        settings = _read_json(os.path.join(dest, "settings.json"))
        settings["workspace"] = open_ws
        _write_json(os.path.join(dest, "settings.json"), settings)


def _import_part(src, dest, report):
    for name in SETTINGS_FILES:
        if os.path.isfile(os.path.join(src, name)):
            _merge_settings(os.path.join(src, name), os.path.join(dest, name), report)
    _copy_missing(src, dest, report, skip=set(SETTINGS_FILES))


# --- the whole thing ------------------------------------------------------------------

def run(data_dir, extra=(), again=False):
    """Imports every old folder found. again: also the ones imported before
    (it still only adds). Returns what it did."""
    mark_path = os.path.join(data_dir, "shell", MARK)
    marks = _read_json(mark_path)
    out = {"sources": [], "teams": 0, "workspaces": [], "files": 0, "errors": []}
    for part, folder in find_sources(data_dir, extra):
        key = f"{part}|{_norm(folder)}"
        mark = marks.get(key) or {}
        if mark.get("at") and not again:
            continue
        report = {"teams": 0, "workspaces": [], "files": 0, "settings": 0}
        try:
            dest = os.path.join(data_dir, part)
            os.makedirs(dest, exist_ok=True)
            if part == "gfxengine":
                _import_engine(folder, dest, mark, report)
            else:
                _import_part(folder, dest, report)
        except Exception as e:   # one folder going wrong mustn't stop the app (or the others)
            log(f"Import from {folder} failed: {e!r}", "error")
            out["errors"].append(f"{folder}: {e}")
            continue
        mark["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        mark["part"], mark["folder"] = part, folder
        marks[key] = mark
        _write_json(mark_path, marks)
        out["sources"].append({"part": part, "folder": folder, "teams": report["teams"],
                               "workspaces": report["workspaces"], "files": report["files"]})
        out["teams"] += report["teams"]
        out["workspaces"] += report["workspaces"]
        out["files"] += report["files"]
        log(f"Imported from {folder} ({part}): {report['teams']} teams, "
            f"{len(report['workspaces'])} workspaces, {report['files']} files")
    if out["sources"] or out["errors"]:
        last = _read_json(mark_path)
        last["_last"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), **out}
        _write_json(mark_path, last)
    return out


def last(data_dir):
    """What was imported, for Settings: {"folders": [...], "last": {...}}."""
    marks = _read_json(os.path.join(data_dir, "shell", MARK))
    return {"folders": [{"part": m.get("part"), "folder": m.get("folder"), "at": m.get("at")}
                        for k, m in marks.items() if not k.startswith("_") and isinstance(m, dict)],
            "last": marks.get("_last")}
