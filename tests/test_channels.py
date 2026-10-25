import unittest

from dexp_dock.channels import HidInterface, select_channels


def iface(pid, col, usage_page=0xFF00, out_len=0, in_len=0, vid=0x3554, mi=1):
    path = r'\\?\hid#vid_%04x&pid_%04x&mi_%02d&col%02d#8&1a2b3c&0&00%02d#{4d1e55b2-f16f-11cf-88cb-001111000030}' % (
        vid, pid, mi, col, col)
    return HidInterface(path=path, vendor_id=vid, product_id=pid, usage_page=usage_page, usage=1,
                        input_length=in_len, output_length=out_len, feature_length=0, product='')


DOCK = [
    iface(0xFB34, 1, usage_page=0x0001),
    iface(0xFB34, 5, out_len=17, in_len=17),
    iface(0xFB34, 8, out_len=40, in_len=40),
]


class SelectChannelsTest(unittest.TestCase):
    def test_picks_command_and_screen_collections_of_the_dock(self):
        channels = select_channels(DOCK)
        self.assertIn('col05', channels.command.path)
        self.assertIn('col08', channels.screen.path)

    def test_ignores_foreign_vendors(self):
        foreign = [iface(0x2203, 5, vid=0x2EA8, out_len=17, in_len=17)]
        self.assertIsNone(select_channels(foreign))

    def test_prefers_device_with_screen_over_wired_mouse(self):
        wired_mouse = [iface(0xFB36, 5, out_len=17, in_len=17)]
        channels = select_channels(wired_mouse + DOCK)
        self.assertEqual(channels.command.product_id, 0xFB34)

    def test_falls_back_to_report_length_when_collection_numbers_differ(self):
        odd = [iface(0xFB34, 3, out_len=17, in_len=17), iface(0xFB34, 4, out_len=40, in_len=40)]
        channels = select_channels(odd)
        self.assertIn('col03', channels.command.path)
        self.assertIn('col04', channels.screen.path)

    def test_device_without_screen_still_gets_command_channel(self):
        channels = select_channels([iface(0xFB34, 5, out_len=17, in_len=17)])
        self.assertIsNotNone(channels.command)
        self.assertIsNone(channels.screen)


if __name__ == '__main__':
    unittest.main()
