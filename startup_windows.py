"""Manage the desktop pet's opt-in Windows sign-in entry for the current user."""

import subprocess
import sys
from pathlib import Path

if sys.platform == 'win32':
    import winreg


RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
ENTRY_NAME = 'CuteDesktopPet'
STARTUP_ARGUMENT = '--autostart'


def startup_command():
    executable = Path(sys.executable).resolve()
    if getattr(sys, 'frozen', False):
        args = [str(executable)]
    else:
        pythonw = executable.with_name('pythonw.exe')
        args = [str(pythonw if pythonw.is_file() else executable), str(Path(sys.argv[0]).resolve())]
    return subprocess.list2cmdline([*args, STARTUP_ARGUMENT])


def registered_command():
    if sys.platform != 'win32':
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            command, _ = winreg.QueryValueEx(key, ENTRY_NAME)
            return command if isinstance(command, str) and command else None
    except FileNotFoundError:
        return None


def set_enabled(enabled):
    if sys.platform != 'win32':
        raise OSError('Windows is required')
    if enabled:
        command = startup_command()
        if len(command) > 260:
            raise OSError('Windows startup command exceeds 260 characters')
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, ENTRY_NAME, 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, ENTRY_NAME)
        except FileNotFoundError:
            pass
