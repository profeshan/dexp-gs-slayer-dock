"""Starts DexpDock hidden in the notification area. Used by the "start with Windows" menu item; works from
any working directory and without a console window when run with pythonw."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dexp_dock.__main__ import main  # noqa: E402

main(['tray'])
