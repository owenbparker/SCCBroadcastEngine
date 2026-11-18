# PyInstaller build for the desktop app.
#
#   pip install -r requirements-windows.txt pyinstaller
#   python apps/multistream/tools/fetch_binaries.py      (MediaMTX and FFmpeg for Multistream)
#   pyinstaller --noconfirm SCCBroadcastEngine.spec
#
# Produces dist/SCCBroadcastEngine/SCCBroadcastEngine.exe (plus its _internal
# folder). The GitHub Actions workflow in .github/workflows/build-windows.yml
# runs this.
import os
import sys

from PyInstaller.utils.hooks import collect_all

root = SPECPATH
icon = os.path.join(root, "packaging", "icon.ico")
apps = os.path.join(root, "apps")

# Each part: (folder in apps/, its package, the folders it reads at run time).
PARTS = [
    ("gfxengine", "gfxengine", ["web", "starter"]),
    ("lolhud", "lolhud", ["web"]),
    ("valhud", "valhud", ["web"]),
    ("codhud", "codhud", ["web"]),
    ("rlhud", "rlhud", ["web"]),
    ("smashhud", "smashhud", ["web"]),
    ("owhud", "owhud", ["web"]),
    ("hudbuilder", "hudbuilder", ["web"]),
    ("multistream", "multistream", ["web", "bin"]),
]

datas = [(os.path.join(root, "web"), "web")]
hidden, binaries, pathex = [], [], [root]
for folder, package, resources in PARTS:
    pathex.append(os.path.join(apps, folder))
    for res in resources:
        src = os.path.join(apps, folder, res)
        if os.path.isdir(src):
            datas.append((src, os.path.join("apps", folder, res)))
        elif res != "bin":
            raise SystemExit(f"Missing {src}")
    # The parts are started by name (sccbe/parts.py), so list every module.
    pkg_dir = os.path.join(apps, folder, package)
    for dirpath, dirnames, filenames in os.walk(pkg_dir):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        rel = os.path.relpath(dirpath, os.path.join(apps, folder)).replace(os.sep, ".")
        for f in filenames:
            if f.endswith(".py"):
                hidden.append(rel if f == "__init__.py" else f"{rel}.{f[:-3]}")

for package in ("imageio_ffmpeg", "psd_tools", "zstandard"):
    d, b, h = collect_all(package)
    datas, binaries, hidden = datas + d, binaries + b, hidden + h
hidden += ["openpyxl", "cryptography", "numpy", "cv2"]
# Code every part shares (one copy: the engine link).
hidden += ["scc_shared", "scc_shared.enginelink", "scc_shared.dpi"]
if sys.platform == "win32":
    # pywebview's Windows window (Edge WebView2) is loaded at runtime.
    hidden += ["webview.platforms.winforms", "webview.platforms.edgechromium", "clr"]
    # Windows text recognition, and capture off the graphics card.
    for package in ("winrt", "dxcam", "comtypes"):
        d, b, h = collect_all(package)
        datas, binaries, hidden = datas + d, binaries + b, hidden + h

a = Analysis(
    [os.path.join(root, "SCCBroadcastEngine.py")],
    pathex=pathex,
    datas=datas,
    binaries=binaries,
    hiddenimports=hidden,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SCCBroadcastEngine",
    console=False,
    icon=icon if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SCCBroadcastEngine")
