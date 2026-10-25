"""Start with Windows: one value under HKCU\\...\\Run (current user only, no administrator rights)."""
import sys
from pathlib import Path

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'DexpDock'
LAUNCHER = Path(__file__).resolve().parent.parent / 'dexp_dock_tray.pyw'


def command(python=None, launcher=LAUNCHER):
    """pythonw.exe (no console window) running the launcher, which does not depend on the working directory."""
    python = Path(python or sys.executable)
    windowless = python.with_name('pythonw.exe')
    return '"%s" "%s"' % (windowless if windowless.exists() else python, launcher)


def is_enabled():
    if sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False


def set_enabled(enabled):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
