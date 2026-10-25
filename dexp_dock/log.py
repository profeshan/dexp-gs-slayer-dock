"""File logging for remote diagnostics: every HID exchange and error lands in dexp-dock.log."""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_NAME = 'dexp-dock.log'
PROGRAM_DIR = Path(__file__).resolve().parent.parent
FALLBACK_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'dexp-dock'

_handler = None


def _open_handler(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LOG_NAME
    return path, RotatingFileHandler(path, maxBytes=1_000_000, backupCount=1, encoding='utf-8')


def setup_logging(directory=PROGRAM_DIR):
    """Log to <directory>/dexp-dock.log, or to %LOCALAPPDATA%/dexp-dock if that is not writable."""
    global _handler
    shutdown()
    try:
        path, handler = _open_handler(Path(directory))
    except OSError:
        path, handler = _open_handler(FALLBACK_DIR)
    handler.setFormatter(logging.Formatter('%(asctime)s %(threadName)s %(levelname)s %(name)s: %(message)s'))
    root = logging.getLogger('dexp_dock')
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    _handler = handler
    return path


def shutdown():
    global _handler
    if _handler is not None:
        logging.getLogger('dexp_dock').removeHandler(_handler)
        _handler.close()
        _handler = None


def stream():
    """Open file object of the current log, for faulthandler dumps."""
    return _handler.stream if _handler is not None else None
