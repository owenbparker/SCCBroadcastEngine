"""Real screen pixels while finding and copying a game window (Windows).

The app window (pywebview) makes the whole process "system DPI aware". Then
Windows gives this process scaled window positions and sizes on any screen
whose display scaling differs from the main screen's (a 4K screen at 150 % or
200 % next to a 1080p one at 100 %), while the screen copy (Pillow's
ImageGrab, the graphics card copy) works in real pixels: the area copied
wasn't the game. Inside `real_pixels()` this thread is per-monitor aware, so
window positions, sizes and screen copies all agree, on every screen.
"""

import contextlib
import ctypes
import sys

PER_MONITOR_AWARE_V2 = -4
PER_MONITOR_AWARE = -3


def _setter():
    if sys.platform != "win32":
        return None
    try:
        f = ctypes.windll.user32.SetThreadDpiAwarenessContext   # Windows 10 1607+
    except AttributeError:
        return None
    f.restype = ctypes.c_void_p
    f.argtypes = [ctypes.c_void_p]
    return f


@contextlib.contextmanager
def real_pixels():
    f = _setter()
    old = None
    if f is not None:
        old = f(ctypes.c_void_p(PER_MONITOR_AWARE_V2)) or f(ctypes.c_void_p(PER_MONITOR_AWARE))
    try:
        yield
    finally:
        if old:
            f(ctypes.c_void_p(old))


def monitors():
    """Each screen's (left, top, right, bottom) in real pixels: the main
    screen first, then left to right (Screen 1, Screen 2, ...)."""
    if sys.platform != "win32":
        return []
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    found = []
    proc = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                              ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def each(hmon, hdc, rect, data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        r = info.rcMonitor
        found.append((not info.dwFlags & 1, r.left, r.top, r.right, r.bottom))
        return 1

    with real_pixels():
        ctypes.windll.user32.EnumDisplayMonitors(None, None, proc(each), 0)
    found.sort(key=lambda m: (m[0], m[1], m[2]))
    return [m[1:] for m in found]


def screen_of(x, y, screens=None):
    """The number (1, 2, ...) of the screen holding the point, or 0."""
    for i, (l, t, r, b) in enumerate(screens if screens is not None else monitors()):
        if l <= x < r and t <= y < b:
            return i + 1
    return 0
