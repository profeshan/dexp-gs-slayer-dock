import sys
import unittest

from dexp_dock.channels import HidInterface


@unittest.skipUnless(sys.platform == 'win32', 'Windows HID stack only')
class EnumerateInterfacesTest(unittest.TestCase):
    def test_enumeration_returns_hid_interfaces(self):
        from dexp_dock import hid_win
        interfaces = hid_win.enumerate_interfaces()
        self.assertIsInstance(interfaces, list)
        for i in interfaces:
            self.assertIsInstance(i, HidInterface)
            self.assertTrue(i.path.startswith('\\\\?\\hid#'), i.path)

    def test_enumeration_reads_ids_and_report_lengths(self):
        from dexp_dock import hid_win
        interfaces = hid_win.enumerate_interfaces()
        if not interfaces:
            self.skipTest('no HID devices present')
        self.assertTrue(any(i.vendor_id != 0 for i in interfaces))
        self.assertTrue(any(i.input_length > 0 for i in interfaces))


if __name__ == '__main__':
    unittest.main()
