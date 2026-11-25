"""Fonts installed on this PC (Windows' Fonts folder, fonts installed "for
this user only", and the usual folders on macOS / Linux), so graphics use
them without adding the file to the engine.

Why the engine reads them itself instead of leaving it to the browser:
- Designs name a font by its PostScript or full name ("Gotham-Bold",
  "Montserrat ExtraBold"), from Photoshop / Figma. CSS font-family only finds
  an installed font by its family name ("Gotham"), so those fell back to Inter.
- WebView2 and OBS's browser don't always see fonts installed for one user
  (%LOCALAPPDATA%\\Microsoft\\Windows\\Fonts), and a browser source on another
  PC doesn't have the font at all.

So each installed font is listed like an added one ({"postscript", "family",
"style", "aliases", "weight", "italic"}) with "system": True, "local" (names
the browser finds it by: CSS local()) and "path" ("sysfonts/<n>/<file>": the
engine serves that file, only from these folders, for when local() fails).
Names are read from the files' name / OS/2 tables, cached by size and time.
"""

import json
import os
import struct
import sys
import threading

from .fonts import _unique

EXTS = (".ttf", ".otf", ".ttc", ".otc")
CACHE_FILE = "system-fonts.json"   # (in the shared library folder)
URL_PREFIX = "sysfonts/"


def font_dirs():
    """The folders installed fonts are in, on this PC."""
    dirs = []
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
        dirs.append(os.path.join(windir, "Fonts"))
        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))   # (installed for this user only)
    elif sys.platform == "darwin":
        dirs += ["/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.local/share/fonts"),
                 os.path.expanduser("~/.fonts")]
    return dirs


def _registry_files():
    """Font files Windows has registered (installers can put them anywhere)."""
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []
    out = []
    key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                i = 0
                while True:
                    try:
                        _, value, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    i += 1
                    if isinstance(value, str) and os.path.isabs(value):
                        out.append(value)
        except OSError:
            continue
    return out


def font_files():
    """Every installed font file (each once)."""
    seen, out = set(), []

    def add(path):
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen and path.lower().endswith(EXTS) and os.path.isfile(path):
            seen.add(key)
            out.append(path)

    for d in font_dirs():
        for folder, dirs, files in os.walk(d):
            dirs[:] = sorted(x for x in dirs if not x.startswith("."))
            for f in sorted(files):
                add(os.path.join(folder, f))
    for path in _registry_files():
        add(path)
    return out


# --- reading a font file's names (only the tables needed, not the whole file) ---

def _tables(f, offset):
    f.seek(offset)
    head = f.read(12)
    if len(head) < 12:
        return {}
    num = struct.unpack(">H", head[4:6])[0]
    raw = f.read(16 * num)
    out = {}
    for i in range(num):
        tag, _, off, length = struct.unpack(">4sIII", raw[16 * i:16 * i + 16])
        out[tag] = (off, length)
    return out


def _read(f, where):
    f.seek(where[0])
    return f.read(min(where[1], 1 << 20))


def _names(table):
    count, string_off = struct.unpack(">HH", table[2:6])
    found = {}
    for i in range(count):
        platform, _, lang, name_id, length, off = struct.unpack(">HHHHHH", table[6 + 12 * i:18 + 12 * i])
        if name_id not in (1, 2, 4, 6, 16, 17):
            continue
        raw = table[string_off + off:string_off + off + length]
        if platform in (0, 3):
            text = raw.decode("utf-16-be", "replace")
            rank = 2 if platform == 3 and lang == 0x409 else 1
        elif platform == 1:
            text = raw.decode("mac_roman", "replace")
            rank = 0
        else:
            continue
        text = text.strip().strip("\x00")
        if text and (name_id not in found or rank > found[name_id][0]):
            found[name_id] = (rank, text)
    return {k: v[1] for k, v in found.items()}


def read_faces(path):
    """[{"postscript", "family", "style", "full", "weight", "italic", "index"}]
    for a font file (several for a collection, .ttc)."""
    out = []
    with open(path, "rb") as f:
        head = f.read(12)
        if head[:4] in (b"ttcf",):
            n = struct.unpack(">I", head[8:12])[0]
            offsets = list(struct.unpack(">%dI" % min(n, 64), f.read(4 * min(n, 64))))
        else:
            offsets = [0]
        for index, offset in enumerate(offsets):
            tables = _tables(f, offset)
            if b"name" not in tables:
                continue
            n = _names(_read(f, tables[b"name"]))
            family = n.get(16) or n.get(1)
            if not family:
                continue
            style = n.get(17) or n.get(2) or "Regular"
            weight, italic = 400, "italic" in style.lower() or "oblique" in style.lower()
            if b"OS/2" in tables:
                os2 = _read(f, tables[b"OS/2"])
                if len(os2) >= 64:
                    weight = struct.unpack(">H", os2[4:6])[0] or 400
                    italic = italic or bool(struct.unpack(">H", os2[62:64])[0] & 1)
            weight = min(900, max(100, int(round(weight / 100.0)) * 100)) if weight >= 50 else 400
            full = n.get(4) or f"{family} {style}"
            out.append({"postscript": n.get(6) or full.replace(" ", "-"), "family": family, "style": style,
                        "full": full, "weight": weight, "italic": italic, "index": index,
                        "legacy": f"{n.get(1)}-{n.get(2)}".replace(" ", "") if n.get(1) else ""})
    return out


class SystemFonts:
    """The installed fonts, read once and kept in library/system-fonts.json."""

    def __init__(self, library_dir=None):
        self.library_dir = library_dir
        self._lock = threading.Lock()
        self._list = None
        self._files = []   # (n -> path, what /sysfonts/<n>/ serves)
        self._seen_dirs = None

    def _cache_path(self):
        return os.path.join(self.library_dir, CACHE_FILE) if self.library_dir else None

    def _load_cache(self):
        p = self._cache_path()
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f) or {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save_cache(self, cache):
        p = self._cache_path()
        if not p:
            return
        try:
            tmp = p + ".part"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            os.replace(tmp, p)
        except OSError:
            pass

    def scan(self):
        cache = self._load_cache()
        fresh, files, fonts = {}, [], []
        for path in font_files():
            try:
                st = os.stat(path)
            except OSError:
                continue
            key = f"{st.st_size}:{int(st.st_mtime)}"
            entry = cache.get(path)
            if not entry or entry.get("key") != key:
                try:
                    entry = {"key": key, "faces": read_faces(path)}
                except (OSError, struct.error, ValueError, IndexError):
                    entry = {"key": key, "faces": []}
            fresh[path] = entry
            if not entry["faces"]:
                continue
            n = len(files)
            files.append(path)
            url = URL_PREFIX + str(n) + "/" + os.path.basename(path)
            for face in entry["faces"]:
                fonts.append(face_entry(face, url if face.get("index", 0) == 0 else None))
        if fresh != cache:
            self._save_cache(fresh)
        return fonts, files

    @staticmethod
    def _dirs_key():
        """Changes when a font is installed or removed (the folders' times)."""
        out = []
        for d in font_dirs():
            try:
                out.append(os.stat(d).st_mtime)
            except OSError:
                out.append(None)
        return out

    def fonts(self, refresh=False):
        with self._lock:
            key = self._dirs_key()
            if self._list is None or refresh or key != self._seen_dirs:
                self._seen_dirs = key
                try:
                    self._list, self._files = self.scan()
                except Exception:
                    self._list, self._files = [], []
            return self._list

    def file(self, rel):
        """The installed font file for "sysfonts/<n>/<name>" (None if it isn't one)."""
        rel = (rel or "").replace("\\", "/").lstrip("/")
        if not rel.startswith(URL_PREFIX):
            return None
        parts = rel[len(URL_PREFIX):].split("/", 1)
        if len(parts) != 2 or not parts[0].isdigit():
            return None
        self.fonts()
        n = int(parts[0])
        if n >= len(self._files) or os.path.basename(self._files[n]) != parts[1]:
            return None
        return self._files[n]


def face_entry(face, url):
    """A font as the pages take it (like an added font's, see assets.fonts)."""
    family, style, full = face["family"], face["style"], face["full"]
    aliases = _unique([face["postscript"], full, full.replace(" ", "-"), full.replace(" ", ""),
                       f"{family}-{style}".replace(" ", ""), f"{family} {style}", face.get("legacy")])
    out = {"postscript": face["postscript"], "family": family, "style": style, "aliases": aliases,
           "weight": face["weight"], "italic": face["italic"], "system": True,
           "local": _unique([face["postscript"], full])}
    if url:
        out["path"] = url
    return out


def known_names(fonts):
    """Every name (lowercase) the installed fonts answer to, families too."""
    return {a.lower() for f in fonts for a in [f.get("family")] + list(f.get("aliases") or []) if a}


_shared = {}
_shared_lock = threading.Lock()


def shared(library_dir=None):
    """One list of installed fonts per library folder (the engine and HUD Builder share it)."""
    with _shared_lock:
        if library_dir not in _shared:
            _shared[library_dir] = SystemFonts(library_dir)
        return _shared[library_dir]
