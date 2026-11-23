"""A whole workspace as one file, to take to another PC (Home > a workspace's
Export, or Send to another engine), and bringing one in (Home > Import).

A .sccws file is a zip:

    scc-ws.json         {"format": "scc-ws", "version": 1, "engine", "name",
                         "teams": [...], "library": [paths], "extras": {...}}
    workspace/...       the workspace's folder: project.json (its graphics,
                        Global, tournaments, schedule, data sources,
                        transitions...), assets/..., its picture, stats
    library/...         the shared files it uses: the fonts its text uses,
                        files it points at in library/, and the teams'
                        logos and players' photos

Importing NEVER changes what's here: the workspace comes in as a new one
(a name that's taken gets " 2"), and isn't opened. Teams are added when
there's no team of that name (and game) here; a team that's here is kept as
it is. A shared file that's here already is used; a different file with
that name comes in under a new name and the workspace points at that.

extras: things that aren't the engine's, added by the app around it (SCC
Broadcast Engine's run of show templates): EXTRAS[key] = (export(), import(data)).
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from .log import log
from .version import VERSION

EXT = ".sccws"
MANIFEST = "scc-ws.json"
FORMAT = "scc-ws"
SKIP_DIRS = {".uploads", "__pycache__"}
SKIP_FILE = re.compile(r"\.(tmp|part)$|^project\.json\.", re.I)
STORED = (".mp4", ".webm", ".mov", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".zip", ".woff2")

# key -> (export() -> JSON-able data or None, import(data) -> a short report dict)
EXTRAS = {}


def _strings(value, out):
    if isinstance(value, dict):
        for v in value.values():
            _strings(v, out)
    elif isinstance(value, list):
        for v in value:
            _strings(v, out)
    elif isinstance(value, str):
        out.add(value)
    return out


def _font_names(value, out):
    """Every "font" value (text layers, Global, HUD looks...)."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k in ("font", "fontFamily", "font_family") and isinstance(v, str) and v:
                out.add(v)
            else:
                _font_names(v, out)
    elif isinstance(value, list):
        for v in value:
            _font_names(v, out)
    return out


def _replace(value, mapping):
    if isinstance(value, dict):
        return {k: _replace(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace(v, mapping) for v in value]
    if isinstance(value, str):
        return mapping.get(value, value)
    return value


def _lib_path(library_dir, rel):
    """library_dir/... on disk for "library/...", or None (never outside it)."""
    rel = (rel or "").replace("\\", "/")
    if not rel.startswith("library/") or not library_dir:
        return None
    path = os.path.normpath(os.path.join(library_dir, rel[len("library/"):]))
    return path if path.startswith(os.path.normpath(library_dir) + os.sep) else None


def safe_name(name, fallback="workspace"):
    """A file name Windows takes, plain ASCII (Chromium ignores filename*)."""
    import unicodedata
    name = unicodedata.normalize("NFKD", str(name or "").replace("·", "-")).encode("ascii", "ignore").decode()
    name = re.sub(r'[\\/:*?"<>|;]+', " ", name)
    return re.sub(r"\s+", " ", name).strip()[:80] or fallback


# --- export -------------------------------------------------------------------------

def build(folder, project, library_dir, teams, fonts, out_path):
    """Writes the .sccws for the workspace in folder to out_path.
    project: its project.json data (the open one's, as it is now).
    teams: the team list. fonts: Assets.fonts() (shared fonts)."""
    refs = {s for s in _strings(project, set()) if s.startswith("library/")}
    for t in teams:
        if str(t.get("logo") or "").startswith("library/"):
            refs.add(t["logo"])
        for p in t.get("players") or []:
            if str(p.get("photo") or "").startswith("library/"):
                refs.add(p["photo"])
    families = _font_names(project, set())
    refs.update(f["path"] for f in fonts
                if str(f.get("path") or "").startswith("library/") and families & set(f.get("aliases") or [f.get("postscript")]))
    library = []
    extras = {}
    for key, (exp, _imp) in EXTRAS.items():
        try:
            data = exp()
        except Exception as e:     # (the workspace still goes)
            log(f"Workspace export: couldn't add {key} ({e!r})")
            continue
        if data:
            extras[key] = data
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        def put(full, arc):
            kind = zipfile.ZIP_STORED if arc.lower().endswith(STORED) else zipfile.ZIP_DEFLATED
            z.write(full, arc, compress_type=kind)

        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".deleted"))
            for n in sorted(files):
                full = os.path.join(root, n)
                rel = os.path.relpath(full, folder).replace(os.sep, "/")
                if rel == "project.json" or SKIP_FILE.search(n):
                    continue
                put(full, "workspace/" + rel)
        z.writestr("workspace/project.json", json.dumps(project, indent=1, ensure_ascii=False))
        for rel in sorted(refs):
            path = _lib_path(library_dir, rel)
            if path and os.path.isfile(path):
                put(path, rel)
                library.append(rel)
        z.writestr(MANIFEST, json.dumps({
            "format": FORMAT, "version": 1, "engine": VERSION, "made": int(time.time()),
            "name": project.get("name", ""), "graphics": len(project.get("compositions") or []),
            "teams": teams, "library": library, "extras": extras}, ensure_ascii=False, indent=1))
    return out_path


# --- import -------------------------------------------------------------------------

def _digest_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _digest_member(z, member):
    h = hashlib.sha1()
    with z.open(member) as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _same(z, member, path):
    return (os.path.isfile(path) and os.path.getsize(path) == z.getinfo(member).file_size
            and _digest_file(path) == _digest_member(z, member))


def _extract(z, member, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with z.open(member) as src, open(dest + ".part", "wb") as out:
        shutil.copyfileobj(src, out, 1 << 20)
    os.replace(dest + ".part", dest)


def read_manifest(path):
    with zipfile.ZipFile(path) as z:
        return _manifest(z)


def _manifest(z):
    try:
        data = json.loads(z.read(MANIFEST).decode("utf-8"))
    except KeyError:
        raise ValueError("That isn't a workspace file (.sccws)") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("That isn't a workspace file (.sccws)")
    if int(data.get("version") or 1) > 1:
        raise ValueError("That workspace was made by a newer version: update this one first")
    return data


def is_package(path):
    try:
        with zipfile.ZipFile(path) as z:
            return MANIFEST in z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def _bring_library(z, files, library_dir):
    """The shared files: kept if here, a different one with that name -> a new name.
    Returns ({old path: new path}, [added])."""
    names = set(z.namelist())
    mapping, added = {}, []
    for rel in files:
        rel = str(rel).replace("\\", "/")
        dest = _lib_path(library_dir, rel)
        if not dest or rel not in names:
            continue
        if os.path.exists(dest):
            if _same(z, rel, dest):
                continue
            base, ext = os.path.splitext(rel)
            n, new = 2, None
            while True:
                cand = f"{base}-{n}{ext}"
                cpath = _lib_path(library_dir, cand)
                if not os.path.exists(cpath):
                    new = cand
                    break
                if _same(z, rel, cpath):    # (brought in before)
                    break
                n += 1
            if new is None:
                mapping[rel] = cand
                continue
            mapping[rel] = new
            dest = _lib_path(library_dir, new)
        _extract(z, rel, dest)
        added.append(mapping.get(rel, rel))
    return mapping, added


def import_package(path, workspaces, library_dir, teams):
    """Adds the workspace in a .sccws as a new workspace (not opened).
    workspaces: the Workspaces. teams: the Teams (or None to leave teams out).
    Returns {"id", "name", "graphics", "teams", "files", "extras"}."""
    with zipfile.ZipFile(path) as z:
        man = _manifest(z)
        try:
            project = json.loads(z.read("workspace/project.json").decode("utf-8"))
        except KeyError:
            raise ValueError("That workspace file has no workspace in it") from None
        if not isinstance(project, dict) or not isinstance(project.get("compositions"), list):
            raise ValueError("That workspace file is damaged")
        mapping, added = _bring_library(z, man.get("library") or [], library_dir)

        # A new folder (never one that's here), and a name that isn't taken.
        base = str(project.get("name") or man.get("name") or "Imported workspace").strip()[:80] or "Imported workspace"
        taken = {w["name"].strip().lower() for w in workspaces.list()}
        name, n = base, 2
        while name.lower() in taken:
            name, n = f"{base} {n}", n + 1
        wid = workspaces._new_id(name)
        folder = os.path.join(workspaces.root, wid)
        tmp = tempfile.mkdtemp(prefix=f".import-{wid}-", dir=workspaces.root)
        try:
            root = os.path.normpath(tmp) + os.sep
            for info in z.infolist():
                m = info.filename
                if not m.startswith("workspace/") or m.endswith("/") or m == "workspace/project.json":
                    continue
                dest = os.path.normpath(os.path.join(tmp, m[len("workspace/"):]))
                if not dest.startswith(root):
                    continue    # (a path out of the folder: never)
                _extract(z, m, dest)
            project = _replace(project, mapping)
            project["name"] = name
            if project.get("picture") and not os.path.isfile(os.path.join(tmp, project["picture"])):
                project["picture"] = ""
            with open(os.path.join(tmp, "project.json"), "w", encoding="utf-8") as f:
                json.dump(project, f, indent=1)
            if os.path.exists(folder):     # (made meanwhile)
                wid = workspaces._new_id(name)
                folder = os.path.join(workspaces.root, wid)
            os.replace(tmp, folder)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    # Teams there's none of here (same name and game): added. Ones here: kept.
    teams_added = []
    if teams is not None and man.get("teams"):
        from .teams import key
        current = teams.list()
        have = {key(t) for t in current}
        for t in man["teams"]:
            if not isinstance(t, dict) or not str(t.get("name") or "").strip():
                continue
            t = _replace(t, mapping)
            if key(t) in have:
                continue
            have.add(key(t))
            teams_added.append(t)
        if teams_added:
            if os.path.isfile(teams.path):
                shutil.copy2(teams.path, teams.path + f".before-import-{time.strftime('%Y%m%d-%H%M%S')}")
            teams.save(current + teams_added)

    extras = {}
    for k, data in (man.get("extras") or {}).items():
        if k in EXTRAS and data:
            try:
                extras[k] = EXTRAS[k][1](data)
            except Exception as e:
                log(f"Workspace import: couldn't bring in {k} ({e!r})")
                extras[k] = {"error": str(e)}
    log(f"Imported the workspace {name} ({wid}): {len(project['compositions'])} graphics, "
        f"{len(teams_added)} new teams, {len(added)} new shared files")
    return {"id": wid, "name": name, "graphics": len(project["compositions"]),
            "teams": [t["name"] for t in teams_added], "files": added, "extras": extras}


# --- straight to another engine -------------------------------------------------------

def send(path, url, name, key=""):
    """Hands a .sccws to another engine's Home > Import (http://PC:port). Returns its answer."""
    from .share import KeyNeeded
    url = url.rstrip("/")
    if not re.match(r"https?://[^/]+$", url):
        raise ValueError("That isn't an engine's address")
    headers = {"X-Filename": urllib.request.quote(safe_name(name) + EXT), "Content-Type": "application/octet-stream",
               "Content-Length": str(os.path.getsize(path))}
    if key:
        headers["X-SCC-Key"] = str(key).strip()
    with open(path, "rb") as f:
        req = urllib.request.Request(url + "/api/workspaces/import", data=f, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                answer = json.loads(e.read())
            except ValueError:
                answer = {}
            msg = answer.get("error") if isinstance(answer, dict) else None
            if isinstance(answer, dict) and answer.get("code") == "key_needed":
                raise KeyNeeded("The other engine wants its pairing code (on that PC: Outputs > Network)") from None
            if e.code == 404:
                raise ValueError("The other PC's SCC Broadcast Engine is too old to take workspaces: update it") from None
            raise ValueError(f"The other engine said: {msg or e.code}") from None
        except (urllib.error.URLError, OSError) as e:
            raise ValueError(f"Couldn't reach the engine at {url} ({getattr(e, 'reason', e)})") from None
