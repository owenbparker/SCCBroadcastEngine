r"""RETIRED (2026-11-15): apps/ is the code now. SCC Broadcast Engine is the
only app going forward, so every change is made in apps/<name>/ in this
repository, and the old app repositories are no longer updated. Copying from
them again would undo work done here, so this refuses to run unless given
--from-old-repos (kept only for bringing in a fix someone made there by hand).

Brings each SCC app's code into apps/<name>/ (the package, its web folder
and anything else it reads at run time), from the app's own repository.

    python tools/sync_apps.py                  every app, from the branches in SOURCES
    python tools/sync_apps.py lolhud valhud    just these
    python tools/sync_apps.py --src lolhud=C:\code\LeagueHUDSCC   from a local clone

Each app keeps its own layout inside apps/<name>/ (apps/lolhud/lolhud,
apps/lolhud/web, ...), so it finds its files the same way it always has. The
copy is changed in three small ways, all listed in PATCHES below:

  * config.py: in the built app, the app's files are in _internal/apps/<name>
    and its settings and data in data/<name> next to SCCBroadcastEngine.exe.
  * updater.py: the app no longer updates itself; SCC Broadcast Engine has
    one updater for everything (sccbe/updater.py).
  * a few pages follow the address bar's #tab, so the top bar can open them
    on the right tab, and load the files in overlays/<name>/ (the app's look
    and behaviour when the page is shown inside the app's window).

apps/SOURCES.json records the repository, branch and commit each copy came from.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.join(ROOT, "apps")

# name: (repository, branch, folders and files to copy)
SOURCES = {
    "gfxengine": ("owenbparker/GFX-Engine", "claude/project-thread-0j8ocb", ["gfxengine", "web", "starter", "tests", "hud-link", "companion-module"]),
    "lolhud": ("owenbparker/LeagueHUDSCC", "claude/project-thread-dvfc00", ["lolhud", "web", "tests", "companion-module", "design"]),
    "valhud": ("owenbparker/VALHUDSCC", "claude/project-thread-dvfc00", ["valhud", "web", "tests"]),
    "codhud": ("owenbparker/COD_SCC_HUD", "claude/project-thread-7aamdb", ["codhud", "web", "tests"]),
    "rlhud": ("owenbparker/RLHUD_SCC", "claude/project-thread-dvfc00", ["rlhud", "web", "tests"]),
    "smashhud": ("owenbparker/SmashHUD_SCC", "claude/project-thread-7aamdb", ["smashhud", "web", "tests"]),
    "owhud": ("owenbparker/OWHUD_SCC", "claude/project-thread-7aamdb", ["owhud", "web", "tests"]),
    # One copy of HUD Builder serves its own page and every game's "Custom design".
    "hudbuilder": ("owenbparker/HUD-Builder", "claude/project-thread-7aamdb", ["hudbuilder", "web", "tests"]),
    "multistream": ("owenbparker/multistream_scc", "claude/project-thread-p3dr1d", ["multistream", "web", "tests", "tools/fetch_binaries.py"]),
}

# Where the files live in the built app, and where each part keeps its data.
CONFIG_RES = 'RESOURCE_DIR = getattr(sys, "_MEIPASS", ROOT) if FROZEN else ROOT'
CONFIG_DATA = "DATA_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else ROOT"


def patch_config(name, text):
    if CONFIG_RES not in text or CONFIG_DATA not in text:
        raise SystemExit(f"{name}/config.py: the RESOURCE_DIR / DATA_DIR lines have changed; update tools/sync_apps.py")
    text = text.replace(CONFIG_RES, (
        "# SCC Broadcast Engine: this part's files are in _internal/apps/" + name + " in the built app\n"
        f'RESOURCE_DIR = os.path.join(getattr(sys, "_MEIPASS", ROOT), "apps", "{name}") if FROZEN else ROOT'))
    text = text.replace(CONFIG_DATA, (
        "# SCC Broadcast Engine: settings and data in data/" + name + " (SCCBE_DATA is set by sccbe/gui.py)\n"
        f'DATA_DIR = (os.path.join(os.environ["SCCBE_DATA"], "{name}") if os.environ.get("SCCBE_DATA") else\n'
        "            os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else ROOT)"))
    return text


def patch_updater(name, text):
    install = 'self.can_install = FROZEN and sys.platform == "win32"'
    if install not in text:
        raise SystemExit(f"{name}/updater.py has changed; update tools/sync_apps.py")
    text = text.replace(install, "self.can_install = False   # SCC Broadcast Engine updates everything (sccbe/updater.py)")
    check = re.search(r"\n    def check\(self\):\n", text)
    if not check:
        raise SystemExit(f"{name}/updater.py has changed; update tools/sync_apps.py")
    return text[:check.end()] + "        return   # SCC Broadcast Engine updates everything (sccbe/updater.py)\n" + text[check.end():]


HASH_FOLLOW = ("\n// SCC Broadcast Engine: the top bar opens a tab by changing the address's #tab,\n"
               "// and the first one shows as soon as the page is ready (not after every picture has loaded).\n"
               "addEventListener(\"hashchange\", () => { const t = location.hash.slice(1); if (t && t !== App.tab) showTab(t); });\n"
               "document.addEventListener(\"DOMContentLoaded\", () => { const t = location.hash.slice(1); if (t && !App.tab) showTab(t); });\n")

EMBED = '<link rel="stylesheet" href="sccbe-embed.css"><script src="sccbe-embed.js"></script>'


def load_embed(t):
    """The overlay's look and behaviour inside the app (overlays/<app>/web/sccbe-embed.*)."""
    if "sccbe-embed.js" in t:
        return t
    if "</head>" not in t:
        raise SystemExit("A page lost its </head>; update tools/sync_apps.py")
    return t.replace("</head>", "<!-- SCC Broadcast Engine (overlays/) -->\n" + EMBED + "\n</head>", 1)


# (app, file inside apps/<app>, function(text) -> text)
PATCHES = [
    ("gfxengine", "web/control.js", lambda t: t if "SCC Broadcast Engine" in t else t + HASH_FOLLOW),
    ("gfxengine", "web/control.html", load_embed),
    ("multistream", "web/index.html", load_embed),
]
OVERLAYS = os.path.join(ROOT, "overlays")


def run(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fetch(repo, branch, tmp):
    """A shallow clone of repo@branch; returns (folder, commit)."""
    dest = os.path.join(tmp, repo.split("/")[1])
    run("git", "clone", "--quiet", "--depth", "1", "--branch", branch, f"https://github.com/{repo}.git", dest)
    return dest, run("git", "rev-parse", "HEAD", cwd=dest)


def copy_app(name, src, commit, record):
    repo, branch, parts = SOURCES[name]
    out = os.path.join(APPS, name)
    shutil.rmtree(out, ignore_errors=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
    for part in parts:
        s, d = os.path.join(src, part), os.path.join(out, part)
        if os.path.isdir(s):
            shutil.copytree(s, d, ignore=ignore)
        elif os.path.isfile(s):
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
        elif part != "tests":
            raise SystemExit(f"{repo}@{branch} has no {part}")
    pkg = parts[0]
    for fname, patch in (("config.py", patch_config), ("updater.py", patch_updater)):
        path = os.path.join(out, pkg, fname)
        with open(path, encoding="utf-8") as f:
            text = patch(name, f.read())
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    overlay = os.path.join(OVERLAYS, name)
    if os.path.isdir(overlay):
        shutil.copytree(overlay, out, dirs_exist_ok=True)
    for app, rel, patch in PATCHES:
        if app == name:
            path = os.path.join(out, rel)
            with open(path, encoding="utf-8") as f:
                text = patch(f.read())
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    record[name] = {"repo": repo, "branch": branch, "commit": commit}
    print(f"{name:12} {repo}@{branch} {commit[:7]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="apps to bring in (default: all)")
    parser.add_argument("--from-old-repos", action="store_true",
                        help="really copy from the old app repositories (overwrites apps/: see the top of this file)")
    parser.add_argument("--src", action="append", default=[], metavar="NAME=FOLDER",
                        help="copy NAME from a local clone instead of GitHub (its checked-out files)")
    args = parser.parse_args()
    if not args.from_old_repos:
        raise SystemExit("apps/ is the code now (see the top of tools/sync_apps.py): make changes there. "
                         "Add --from-old-repos to copy from the old repositories anyway.")
    names = args.names or list(SOURCES)
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        raise SystemExit(f"Unknown: {', '.join(unknown)} (know: {', '.join(SOURCES)})")
    local = dict(s.split("=", 1) for s in args.src)
    record_path = os.path.join(APPS, "SOURCES.json")
    record = {}
    if os.path.exists(record_path):
        with open(record_path, encoding="utf-8") as f:
            record = json.load(f)
    os.makedirs(APPS, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            if name in local:
                src = local[name]
                commit = run("git", "rev-parse", "HEAD", cwd=src)
                if run("git", "status", "--porcelain", cwd=src):
                    commit += "+local changes"
            else:
                repo, branch, _ = SOURCES[name]
                src, commit = fetch(repo, branch, tmp)
            copy_app(name, src, commit, record)
    with open(record_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(sorted(record.items())), f, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
