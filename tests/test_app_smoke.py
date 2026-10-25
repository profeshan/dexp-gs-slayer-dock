import sys
import time
import unittest

from dexp_dock.i18n import Translator, load_locale


@unittest.skipUnless(sys.platform == 'win32', 'Windows HID stack only')
class AppSmokeTest(unittest.TestCase):
    def test_window_reports_missing_dock(self):
        import tkinter as tk
        from dexp_dock import app
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        tr = Translator(load_locale('ru'))
        window = app.App(root, tr)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and window.status.get() == tr('status.searching'):
            root.update()
            time.sleep(0.05)
        status = window.status.get()
        root.destroy()
        connected_prefix = tr('status.connected', product='', pid='').split(':')[0]
        if not status.startswith(connected_prefix):
            self.assertEqual(status, tr('status.not_found'))


if __name__ == '__main__':
    unittest.main()
