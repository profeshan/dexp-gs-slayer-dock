import datetime
import unittest

from dexp_dock import protocol

MOMENT = datetime.datetime(2026, 1, 3, 3, 13, 0)  # Saturday -> ISO weekday 6


class ClockVariantTest(unittest.TestCase):
    def variant(self, number):
        return protocol.build_screen_clock_variant(number, MOMENT)

    def test_all_variants_are_full_reports_with_screen_report_id(self):
        for number in protocol.CLOCK_VARIANTS:
            packet = self.variant(number)
            self.assertEqual(len(packet), 40, number)
            self.assertEqual(packet[0], 0x0A, number)

    def test_variant_1_is_the_vendor_layout(self):
        self.assertEqual(self.variant(1), protocol.build_screen_clock(MOMENT))

    def test_variant_2_puts_checksum_right_after_the_data(self):
        packet = self.variant(2)
        self.assertEqual(packet[:11], bytes([0x0A, 0x00, 0x10, 0x07, 0xEA, 1, 3, 3, 13, 0, 6]))
        self.assertEqual(packet[11], protocol.checksum(packet[:11]))
        self.assertEqual(packet[12:], bytes(28))

    def test_variant_3_has_command_in_byte_1(self):
        packet = self.variant(3)
        self.assertEqual(packet[:10], bytes([0x0A, 0x10, 0x07, 0xEA, 1, 3, 3, 13, 0, 6]))
        self.assertEqual(packet[39], protocol.checksum(packet[:39]))

    def test_variant_4_has_command_in_byte_1_and_short_checksum(self):
        packet = self.variant(4)
        self.assertEqual(packet[:10], bytes([0x0A, 0x10, 0x07, 0xEA, 1, 3, 3, 13, 0, 6]))
        self.assertEqual(packet[10], protocol.checksum(packet[:10]))
        self.assertEqual(packet[11:], bytes(29))

    def test_variant_5_checksum_skips_report_id(self):
        packet = self.variant(5)
        self.assertEqual(packet[:11], protocol.build_screen_clock(MOMENT)[:11])
        self.assertEqual(packet[39], protocol.checksum(packet[1:39]))

    def test_variant_6_uses_one_byte_year(self):
        packet = self.variant(6)
        self.assertEqual(packet[:10], bytes([0x0A, 0x00, 0x10, 26, 1, 3, 3, 13, 0, 6]))
        self.assertEqual(packet[39], protocol.checksum(packet[:39]))

    def test_marker_time_identifies_the_variant(self):
        base = datetime.datetime(2026, 9, 20, 18, 0, 0)
        self.assertEqual(protocol.variant_marker_time(4, base), datetime.datetime(2026, 1, 4, 4, 14, 0))


if __name__ == '__main__':
    unittest.main()
