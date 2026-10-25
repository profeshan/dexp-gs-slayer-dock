import sys
import tempfile
import time
import unittest
from pathlib import Path

from dexp_dock import autostart, tray


class IconPixelsTest(unittest.TestCase):
    def test_buffer_has_four_bytes_per_pixel(self):
        self.assertEqual(len(tray.icon_pixels((255, 0, 0))), tray.ICON_SIZE * tray.ICON_SIZE * 4)

    def test_centre_has_the_colour_and_corners_are_transparent(self):
        size = tray.ICON_SIZE
        pixels = tray.icon_pixels((255, 255, 0))

        def pixel(x, y):
            offset = (y * size + x) * 4
            return tuple(pixels[offset:offset + 4])  # B, G, R, A

        self.assertEqual(pixel(size // 2, size // 2), (0, 255, 255, 255))
        self.assertEqual(pixel(0, 0)[3], 0)
        self.assertEqual(pixel(size - 1, size - 1)[3], 0)

    def test_colour_is_premultiplied_by_alpha(self):
        size = tray.ICON_SIZE
        pixels = tray.icon_pixels((255, 255, 255))
        for i in range(0, len(pixels), 4):
            blue, green, red, alpha = pixels[i:i + 4]
            self.assertLessEqual(max(blue, green, red), alpha)

    def test_hex_colour_parsing_falls_back_to_grey(self):
        self.assertEqual(tray.parse_hex_color('#FFFF00'), (255, 255, 0))
        self.assertEqual(tray.parse_hex_color('00ff7f'), (0, 255, 127))
        self.assertEqual(tray.parse_hex_color('nonsense'), (128, 128, 128))
        self.assertEqual(tray.parse_hex_color(None), (128, 128, 128))


class AutostartCommandTest(unittest.TestCase):
    def test_uses_pythonw_next_to_the_interpreter_and_quotes_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            python = Path(folder) / 'python.exe'
            pythonw = Path(folder) / 'pythonw.exe'
            python.write_text('')
            pythonw.write_text('')
            launcher = Path(folder) / 'my folder' / 'dexp_dock_tray.pyw'
            self.assertEqual(autostart.command(python, launcher), '"%s" "%s"' % (pythonw, launcher))

    def test_falls_back_to_the_interpreter_without_pythonw(self):
        with tempfile.TemporaryDirectory() as folder:
            python = Path(folder) / 'python.exe'
            python.write_text('')
            self.assertEqual(autostart.command(python, Path('x.pyw')), '"%s" "x.pyw"' % python)

    def test_the_launcher_exists_in_the_project(self):
        self.assertTrue(autostart.LAUNCHER.exists())


@unittest.skipUnless(sys.platform == 'win32', 'Windows shell only')
class TrayIconTest(unittest.TestCase):
    def setUp(self):
        self.icon = tray.TrayIcon(lambda key, **kw: key)
        if not self.icon.start():
            self.skipTest('no notification area available')
        self.addCleanup(self.icon.close)

    def wait_for_events(self, expected, timeout=2.0):
        events = []
        end = time.monotonic() + timeout
        while time.monotonic() < end and expected not in events:
            events += self.icon.pop_events()
            time.sleep(0.02)
        return events

    def test_message_from_a_second_instance_becomes_a_show_event(self):
        tray.user32.PostMessageW(self.icon._hwnd, tray.WM_SHOW, 0, 0)
        self.assertIn('show', self.wait_for_events('show'))

    def test_state_changes_are_accepted_without_errors(self):
        self.icon.set_state('#FFFF00', 'Уровень DPI: 2 из 2 (2500 DPI)', True, False)
        self.icon.set_state('#808080', 'x' * 500, False, True)  # a tooltip longer than the shell allows
        time.sleep(0.2)
        self.assertTrue(self.icon._added)

    def test_close_removes_the_icon_and_stops_the_thread(self):
        self.icon.close()
        self.assertFalse(self.icon._thread.is_alive())
        self.assertFalse(self.icon._added)


if __name__ == '__main__':
    unittest.main()
