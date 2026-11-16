"""The main window has no Windows title bar (it showed the Windows accent
colour above the app's own top bar). The page draws minimise / maximise /
close in a glass capsule next to the top bar and calls these through
pywebview's js_api (window.pywebview.api.win_*).

On Windows the window is moved, sized and maximised with Win32 calls in
physical pixels, so it works the same at any display scale; "maximised" fills
the monitor's work area (a borderless window maximised by Windows would cover
the taskbar). Elsewhere pywebview's own calls are used.
"""

import sys

WIN = sys.platform == "win32"

if WIN:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.MonitorFromWindow.restype = wintypes.HMONITOR
    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.IsIconic.argtypes = [wintypes.HWND]

GWL_STYLE = -16
WS_MINIMIZEBOX = 0x00020000
WS_SYSMENU = 0x00080000
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x4, 0x10, 0x20


def clamp_rect(x, y, w, h, min_w, min_h):
    """A window rectangle no smaller than the minimum size."""
    return int(x), int(y), max(int(w), int(min_w)), max(int(h), int(min_h))


def restore_rect_for_drag(saved, cursor_x, cursor_y, ratio):
    """Where the window goes when it's dragged out of maximised: its old size,
    with the cursor at the same place across the bar as it grabbed it."""
    x, y, w, h = saved
    nx = int(cursor_x - w * min(max(ratio, 0.0), 1.0))
    return nx, int(cursor_y - 20), w, h


class WindowApi:
    """js_api for the main window. Attributes start with _ so pywebview only
    exposes the win_* methods."""

    def __init__(self, min_size=(1100, 680)):
        self._window = None
        self._min = min_size
        self._saved = None        # the rectangle to go back to from maximised
        self._hwnd_cache = None

    def _attach(self, window):
        self._window = window
        window.events.shown += self._on_shown

    # -- Win32 ----------------------------------------------------------------
    def _hwnd(self):
        if not WIN:
            return None
        if self._hwnd_cache:
            return self._hwnd_cache
        try:
            native = self._window.native
            h = native.Handle
            self._hwnd_cache = int(h.ToInt64()) if hasattr(h, "ToInt64") else int(h)
        except Exception:
            self._hwnd_cache = None
        return self._hwnd_cache

    def _on_shown(self):
        # A borderless window has no minimise box, so its taskbar button can't
        # minimise it, and no system menu (Alt+Space). Give it both back; they
        # don't draw anything.
        hwnd = self._hwnd()
        if not hwnd:
            return
        try:
            style = _user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            _user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style | WS_MINIMIZEBOX | WS_SYSMENU)
            _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOSIZE | 0x2 | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        except Exception:
            pass

    def _rect(self, hwnd):
        r = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(r))
        return r.left, r.top, r.right - r.left, r.bottom - r.top

    def _work_area(self, hwnd):
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        _user32.GetMonitorInfoW(_user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
        w = mi.rcWork
        return w.left, w.top, w.right - w.left, w.bottom - w.top

    def _place(self, hwnd, x, y, w, h, size=True):
        _user32.SetWindowPos(hwnd, None, int(x), int(y), int(w), int(h),
                             SWP_NOZORDER | SWP_NOACTIVATE | (0 if size else SWP_NOSIZE))

    # -- called from the page ---------------------------------------------------
    def win_state(self):
        return {"native": True, "maximized": self._saved is not None}

    def win_minimize(self):
        self._window.minimize()

    def win_close(self):
        self._window.destroy()

    def win_toggle_max(self):
        hwnd = self._hwnd()
        if not hwnd:
            if self._saved is None:
                self._saved = True
                self._window.maximize()
            else:
                self._saved = None
                self._window.restore()
            return self.win_state()
        if self._saved is not None:
            self._place(hwnd, *self._saved)
            self._saved = None
        else:
            self._saved = self._rect(hwnd)
            self._place(hwnd, *self._work_area(hwnd))
        return self.win_state()

    def win_rect(self):
        """The window's rectangle in physical pixels (None off Windows)."""
        hwnd = self._hwnd()
        return list(self._rect(hwnd)) if hwnd else None

    def win_move(self, x, y):
        hwnd = self._hwnd()
        if hwnd:
            self._place(hwnd, x, y, 0, 0, size=False)
        else:
            self._window.move(int(x), int(y))

    def win_drag_out(self, cursor_x, cursor_y, ratio):
        """The bar was dragged while maximised: back to the old size under the
        cursor. Returns the new rectangle so the page carries on dragging it."""
        hwnd = self._hwnd()
        if not hwnd or not isinstance(self._saved, tuple):
            self._saved = None
            return None
        rect = restore_rect_for_drag(self._saved, cursor_x, cursor_y, ratio)
        self._saved = None
        self._place(hwnd, *rect)
        return list(rect)

    def win_set_rect(self, x, y, w, h, scale=1.0):
        hwnd = self._hwnd()
        mw, mh = self._min[0] * float(scale or 1), self._min[1] * float(scale or 1)
        x, y, w, h = clamp_rect(x, y, w, h, mw, mh)
        if hwnd:
            self._saved = None
            self._place(hwnd, x, y, w, h)
