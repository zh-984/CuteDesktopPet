"""Identify the active Windows window without reading its contents or title."""

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
