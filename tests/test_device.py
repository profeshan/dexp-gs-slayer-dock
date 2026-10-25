import unittest

from dexp_dock import device
from dexp_dock.channels import select_channels
from dexp_dock.i18n import Translator, load_locale
from tests.test_channels import DOCK, iface


class ParseColorTest(unittest.TestCase):
    def test_parses_hex_with_and_without_hash(self):
        self.assertEqual(device.parse_color('#ff8000'), (255, 128, 0))
        self.assertEqual(device.parse_color('00FF7f'), (0, 255, 127))

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            device.parse_color('orange')


class DiagnosticsReportTest(unittest.TestCase):
    def setUp(self):
        self.tr = Translator(load_locale('en'))

    def test_report_lists_dock_interfaces_and_selected_channels(self):
        interfaces = DOCK + [iface(0x2203, 5, vid=0x2EA8)]
        text = device.diagnostics_report(interfaces, select_channels(interfaces), self.tr, report_ids={})
        self.assertIn('HID interfaces with VID 0x3554: 3', text)
        self.assertIn('col05', text.split('Command channel:')[1].splitlines()[0])
        self.assertIn('col08', text.split('Screen channel:')[1].splitlines()[0])
        self.assertNotIn('vid_2ea8', text)

    def test_report_without_dock(self):
        text = device.diagnostics_report([], None, self.tr, report_ids={})
        self.assertIn('Command channel: not found', text)
        self.assertIn('Screen channel: not found', text)


if __name__ == '__main__':
    unittest.main()
