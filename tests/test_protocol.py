import datetime
import unittest

from dexp_dock import protocol


def bytes_from_hex(text):
    return bytes.fromhex(text.replace(' ', ''))


class ChecksumTest(unittest.TestCase):
    def test_checksum_is_0x55_minus_byte_sum(self):
        # 0x08 + 0x18 + 0x0A = 0x2A -> 0x55 - 0x2A = 0x2B
        self.assertEqual(protocol.checksum(bytes([0x08, 0x18, 0x0A])), 0x2B)

    def test_checksum_wraps_to_one_byte(self):
        # 0xFF + 0xFF = 0x1FE -> low byte 0xFE -> 0x55 - 0xFE = -0xA9 -> 0x57
        self.assertEqual(protocol.checksum(bytes([0xFF, 0xFF])), 0x57)


class DockLightPacketTest(unittest.TestCase):
    def test_set_dock_light_layout(self):
        packet = protocol.build_set_dock_light(
            protocol.DockLight(mode=3, red=255, green=0, blue=0, speed=5, brightness=10))
        # sum = 08+18+0A+03+FF+04+09 = 0x139 -> 0x39 -> 0x55-0x39 = 0x1C
        expected = bytes_from_hex('08 18 00 00 00 0A 03 FF 00 00 04 09 00 00 00 00 1C')
        self.assertEqual(packet, expected)

    def test_set_dock_light_off_sends_mode_zero(self):
        packet = protocol.build_set_dock_light(
            protocol.DockLight(mode=0, red=1, green=2, blue=3, speed=1, brightness=1))
        self.assertEqual(packet[6], 0)
        self.assertEqual(packet[7:12], bytes([1, 2, 3, 0, 0]))

    def test_set_dock_light_rejects_out_of_range_brightness(self):
        with self.assertRaises(ValueError):
            protocol.build_set_dock_light(
                protocol.DockLight(mode=1, red=0, green=0, blue=0, speed=1, brightness=11))

    def test_get_dock_light_request(self):
        # sum = 08+19 = 0x21 -> 0x55-0x21 = 0x34
        expected = bytes_from_hex('08 19 00 00 00 00 00 00 00 00 00 00 00 00 00 00 34')
        self.assertEqual(protocol.build_get_dock_light(), expected)

    def test_parse_dock_light_response(self):
        body = bytearray(bytes_from_hex('08 19 00 00 00 07 04 10 20 30 02 06 01 00 00 00 00'))
        body[16] = protocol.checksum(body[:16])
        light = protocol.parse_dock_light(bytes(body))
        self.assertEqual(light, protocol.DockLight(
            mode=4, red=0x10, green=0x20, blue=0x30, speed=3, brightness=7))

    def test_parse_dock_light_rejects_bad_checksum(self):
        body = bytearray(bytes_from_hex('08 19 00 00 00 07 04 10 20 30 02 06 01 00 00 00 00'))
        body[16] = (protocol.checksum(body[:16]) + 1) & 0xFF
        with self.assertRaises(protocol.ProtocolError):
            protocol.parse_dock_light(bytes(body))


class IndicatorPacketTest(unittest.TestCase):
    def test_set_indicator_layout(self):
        packet = protocol.build_set_indicator((2, 1, 4))
        # sum = 08+2C+0A+02+01+04 = 0x45 -> 0x55-0x45 = 0x10
        expected = bytes_from_hex('08 2C 00 00 00 0A 02 01 04 00 00 00 00 00 00 00 10')
        self.assertEqual(packet, expected)

    def test_parse_indicator_response(self):
        body = bytearray(17)
        body[0:9] = bytes([0x08, 0x2D, 0, 0, 0, 3, 3, 0, 1])
        body[16] = protocol.checksum(body[:16])
        self.assertEqual(protocol.parse_indicator(bytes(body)), (3, 0, 1))


class ResponseValidationTest(unittest.TestCase):
    def test_response_must_echo_command(self):
        body = bytearray(17)
        body[0:2] = bytes([0x08, 0x18])
        body[16] = protocol.checksum(body[:16])
        self.assertTrue(protocol.is_valid_response(bytes(body), 0x18))
        self.assertFalse(protocol.is_valid_response(bytes(body), 0x19))

    def test_short_response_is_invalid(self):
        self.assertFalse(protocol.is_valid_response(bytes([0x08, 0x18]), 0x18))


class ScreenClockPacketTest(unittest.TestCase):
    def test_clock_packet_layout(self):
        # 2026-09-19 is a Saturday -> ISO weekday 6 (Qt dayOfWeek uses the same numbering).
        moment = datetime.datetime(2026, 9, 19, 22, 45, 7)
        packet = protocol.build_screen_clock(moment)
        self.assertEqual(len(packet), 40)
        head = bytes_from_hex('0A 00 10 07 EA 09 13 16 2D 07 06')
        self.assertEqual(packet[:11], head)
        self.assertEqual(packet[11:39], bytes(28))
        # sum = 0A+10+07+EA+09+13+16+2D+07+06 = 0x177 -> 0x77 -> 0x55-0x77 = 0xDE
        self.assertEqual(packet[39], 0xDE)

    def test_clock_packet_follows_report_length(self):
        moment = datetime.datetime(2026, 1, 2, 3, 4, 5)
        packet = protocol.build_screen_clock(moment, length=33, report_id=0x0B)
        self.assertEqual(len(packet), 33)
        self.assertEqual(packet[0], 0x0B)
        self.assertEqual(packet[32], protocol.checksum(packet[:32]))


if __name__ == '__main__':
    unittest.main()
