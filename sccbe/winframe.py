"""The main window has no Windows title bar (it showed the Windows accent
colour above the app's own top bar). The page draws minimise / maximise /
close in a glass capsule next to the top bar and calls these through
pywebview's js_api (window.pywebview.api.win_*).

On Windows the window gets the styles of a normal window back (sizing frame,
caption, maximise box) and its window procedure is subclassed so the frame
takes no space (WM_NCCALCSIZE). Dragging the top bar or an edge then hands
the mouse to Windows' own move / size loop (WM_NCLBUTTONDOWN with HTCAPTION or
an edge), so Windows Snap works like any app: drag to the top to maximise, to
a side for half the screen, Snap Layouts, Win+arrows, and dragging a
maximised window down restores it. Maximised fills the monitor's work area
(the taskbar stays visible). If that set-up fails the page falls back to
moving the window itself (the old way, no Snap). Elsewhere pywebview's own
calls are used.
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
    _user32.IsZoomed.argtypes = [wintypes.HWND]
    _user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.CallWindowProcW.restype = ctypes.c_ssize_t
    _user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class _NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

    class _STYLESTRUCT(ctypes.Structure):
        _fields_ = [("styleOld", wintypes.DWORD), ("styleNew", wintypes.DWORD)]

GWL_STYLE = -16
GWLP_WNDPROC = -4
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_CAPTION = 0x00C00000
# The styles Windows looks for before it snaps, maximises or animates a window.
SNAP_STYLES = WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MAXIMIZEBOX | WS_MINIMIZEBOX
WM_NCCALCSIZE, WM_NCDESTROY, WM_STYLECHANGING, WM_NCLBUTTONDOWN = 0x0083, 0x0082, 0x007C, 0x00A1
WM_APP_WIN = 0x8000 + 0x5C   # ours: wParam 1 = start a drag/size (lParam = hit-test code), 2 = maximise/restore
HTCAPTION = 2
# The edge names the page uses -> Windows' hit-test codes for that edge.
EDGE_HIT = {"w": 10, "e": 11, "n": 12, "nw": 13, "ne": 14, "s": 15, "sw": 16, "se": 17}
SW_MAXIMIZE, SW_RESTORE = 3, 9
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x4, 0x10, 0x20


def clamp_rect(x, y, w, h, min_w, min_h):
    """A window rectangle no smaller than the minimum size."""
    return int(x), int(y), max(int(w), int(min_w)), max(int(h), int(min_h))


def hit_code(edge):
    """Windows' hit-test code for a drag from this part of the window:
    '' / 'caption' = the title bar, else an edge name like 'n' or 'se'."""
    if not edge or edge == "caption":
        return HTCAPTION
    return EDGE_HIT.get(str(edge).lower())


def points_lparam(x, y):
    """A screen point packed the way WM_NCLBUTTONDOWN wants it (signed 16-bit
    x and y, so monitors left of / above the main one work)."""
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


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
        self._snap = False        # Windows' own move/size/maximise (Snap) is set up
        self._old_proc = None
        self._proc_ref = None     # keeps the ctypes window procedure alive

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
        hwnd = self._hwnd()
        if not hwnd:
            return
        try:
            self._snap = self._subclass(hwnd)
        except Exception:
            self._snap = False
        try:
            # Without the Snap set-up, still give the borderless window a
            # minimise box (its taskbar button minimises it) and a system menu
            # (Alt+Space). They don't draw anything.
            extra = SNAP_STYLES if self._snap else (WS_MINIMIZEBOX | WS_SYSMENU)
            style = _user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            _user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style | extra)
            _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOSIZE | 0x2 | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        except Exception:
            pass

    def _subclass(self, hwnd):
        """Put our window procedure in front of the window's own one."""
        if self._old_proc:
            return True

        def proc(h, msg, wp, lp):
            try:
                r = self._wndproc(h, msg, wp, lp)
                if r is not None:
                    return r
            except Exception:
                pass
            return _user32.CallWindowProcW(self._old_proc, h, msg, wp, lp)

        self._proc_ref = _WNDPROC(proc)
        addr = ctypes.cast(self._proc_ref, ctypes.c_void_p).value
        old = _user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, addr)
        if not old:
            self._proc_ref = None
            return False
        self._old_proc = old
        return True

    def _wndproc(self, h, msg, wp, lp):
        """Our part of the window procedure; None = let the window's own one have it."""
        if msg == WM_NCCALCSIZE and wp:
            # The whole window is the page: no frame, no caption. Maximised, the
            # window hangs over the screen edges by the frame's width, so the
            # page is fitted to the monitor's work area instead.
            if _user32.IsZoomed(h):
                p = ctypes.cast(lp, ctypes.POINTER(_NCCALCSIZE_PARAMS)).contents
                x, y, w, hh = self._work_area(h)
                p.rgrc[0].left, p.rgrc[0].top, p.rgrc[0].right, p.rgrc[0].bottom = x, y, x + w, y + hh
            return 0
        if msg == WM_STYLECHANGING and (int(wp) & 0xFFFFFFFF) == (GWL_STYLE & 0xFFFFFFFF):
            # If the window library rewrites the styles, keep the Snap ones.
            ss = ctypes.cast(lp, ctypes.POINTER(_STYLESTRUCT)).contents
            ss.styleNew = ss.styleNew | SNAP_STYLES
            return None
        if msg == WM_APP_WIN:
            # Runs on the window's own thread, which is where this has to happen.
            if wp == 1:
                pt = wintypes.POINT()
                _user32.GetCursorPos(ctypes.byref(pt))
                _user32.ReleaseCapture()
                _user32.PostMessageW(h, WM_NCLBUTTONDOWN, int(lp), points_lparam(pt.x, pt.y))
            elif wp == 2:
                _user32.ShowWindowAsync(h, SW_RESTORE if _user32.IsZoomed(h) else SW_MAXIMIZE)
            return 0
        if msg == WM_NCDESTROY and self._old_proc:
            old = self._old_proc
            _user32.SetWindowLongPtrW(h, GWLP_WNDPROC, old)
            self._old_proc = None
            return _user32.CallWindowProcW(old, h, msg, wp, lp)
        return None

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
        hwnd = self._hwnd() if self._snap else None
        if hwnd:
            return {"native": True, "snap": True, "maximized": bool(_user32.IsZoomed(hwnd))}
        return {"native": True, "snap": False, "maximized": self._saved is not None}

    def win_begin(self, edge=""):
        """The mouse went down on the top bar ('caption') or an edge ('n', 'se'
        ...): Windows takes over the drag, with Snap. False = do it the old way."""
        hwnd = self._hwnd() if self._snap else None
        code = hit_code(edge)
        if not hwnd or code is None:
            return False
        return bool(_user32.PostMessageW(hwnd, WM_APP_WIN, 1, code))

    def win_minimize(self):
        self._window.minimize()

    def win_close(self):
        self._window.destroy()

    def win_toggle_max(self):
        hwnd = self._hwnd()
        if hwnd and self._snap:
            # Windows' own maximise: Win+Down, the restore size and Snap all agree with it.
            was = bool(_user32.IsZoomed(hwnd))
            _user32.PostMessageW(hwnd, WM_APP_WIN, 2, 0)
            return {"native": True, "snap": True, "maximized": not was}
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
