"""Windows foreground and physical desktop geometry helpers."""

import ctypes
import os
import sys
from ctypes import wintypes


if sys.platform == 'win32':
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD),
                    ('device', wintypes.WCHAR * 32)]

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetClassNameW.restype = ctypes.c_int
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MonitorInfo))
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    MonitorCallback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                       ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    user32.EnumDisplayMonitors.argtypes = (wintypes.HDC, ctypes.POINTER(wintypes.RECT), MonitorCallback, wintypes.LPARAM)
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT)
    user32.SetWindowPos.restype = wintypes.BOOL


def window_pid(handle):
    if sys.platform != 'win32' or not handle:
        return 0
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    return pid.value


def foreground_window():
    """Return (root owner HWND, PID, is desktop/taskbar), or None during activation."""
    if sys.platform != 'win32':
        return None
    handle = user32.GetForegroundWindow()
    if not handle:
        return None
    handle = user32.GetAncestor(handle, 3) or handle  # GA_ROOTOWNER groups owned dialogs.
    pid = window_pid(handle)
    if not pid or pid == os.getpid():
        return None
    class_name = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(handle, class_name, len(class_name))
    shell = class_name.value in {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}
    return handle, pid, shell


def window_monitor(handle):
    if sys.platform != 'win32':
        return ''
    monitor = user32.MonitorFromWindow(handle, 2)  # MONITOR_DEFAULTTONEAREST
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    return info.device if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)) else ''


def physical_displays():
    rects = {}
    if sys.platform != 'win32':
        return rects

    @MonitorCallback
    def collect(monitor, _dc, _rect, _data):
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect = info.monitor
            rects[info.device.casefold()] = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        return True

    user32.EnumDisplayMonitors(None, None, collect, 0)
    return rects


def physical_cursor():
    point = wintypes.POINT()
    return (point.x, point.y) if user32.GetCursorPos(ctypes.byref(point)) else None


def physical_window_rect(handle):
    rect = wintypes.RECT()
    if user32.GetWindowRect(handle, ctypes.byref(rect)):
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    return None


def move_window_anchor(handle, x, y, fraction_x=0.5, fraction_y=0.5):
    """Keep the same grab point when Qt applies a new window size at a DPI seam."""
    flags = 0x0001 | 0x0004 | 0x0010 | 0x0200  # Keep size, Z order, focus, and owner order.
    for _ in range(2):
        rect = physical_window_rect(handle)
        if rect is None:
            return False
        left, top, width, height = rect
        dest = round(x - width * fraction_x), round(y - height * fraction_y)
        if dest == (left, top):
            return True
        if not user32.SetWindowPos(handle, None, *dest, 0, 0, flags):
            return False
        changed = physical_window_rect(handle)
        if changed is None or changed[2:] == rect[2:]:
            return changed is not None
    return True
