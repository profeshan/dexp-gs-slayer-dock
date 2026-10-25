import datetime
import unittest

from dexp_dock import protocol
from dexp_dock.client import DockClient, DeviceTimeout


def reply(cmd, payload=b'', length_byte=0x0A):
    body = bytearray(17)
    body[0] = 0x08
    body[1] = cmd
    body[5] = length_byte
    body[6:6 + len(payload)] = payload
    body[16] = protocol.checksum(body[:16])
    return bytes(body)


class FakePort:
    def __init__(self, output_length=17, replies=None, report_id=None):
        self.output_length = output_length
        self.report_id = report_id
        self.written = []
        self.replies = list(replies or [])

    def write(self, data):
        self.written.append(bytes(data))

    def read(self, timeout_ms):
        return self.replies.pop(0) if self.replies else None

    def drain(self):
        pass


class DockLightClientTest(unittest.TestCase):
    def test_read_dock_light_skips_unrelated_reports(self):
        noise = reply(0x04, b'\x64')
        answer = reply(protocol.CMD_GET_DOCK_LIGHT, bytes([3, 255, 128, 0, 4, 9, 1]), length_byte=7)
        port = FakePort(replies=[noise, answer])
        light = DockClient(command_port=port).read_dock_light()
        self.assertEqual(light, protocol.DockLight(mode=3, red=255, green=128, blue=0, speed=5, brightness=10))
        self.assertEqual(port.written, [protocol.build_get_dock_light()])

    def test_set_dock_light_sends_packet_and_accepts_echo(self):
        light = protocol.DockLight(mode=1, red=0, green=0, blue=255, speed=3, brightness=8)
        port = FakePort(replies=[reply(protocol.CMD_SET_DOCK_LIGHT)])
        DockClient(command_port=port).set_dock_light(light)
        self.assertEqual(port.written, [protocol.build_set_dock_light(light)])

    def test_silent_dock_is_retried_then_times_out(self):
        port = FakePort(replies=[])
        with self.assertRaises(DeviceTimeout):
            DockClient(command_port=port).read_dock_light()
        self.assertEqual(len(port.written), 2)

    def test_command_packet_is_padded_to_report_length(self):
        port = FakePort(output_length=20, replies=[reply(protocol.CMD_SET_INDICATOR)])
        DockClient(command_port=port).set_indicator((1, 2, 3))
        self.assertEqual(len(port.written[0]), 20)
        self.assertEqual(port.written[0][:17], protocol.build_set_indicator((1, 2, 3)))


class RejectedCommandTest(unittest.TestCase):
    def test_nonzero_status_byte_means_command_rejected(self):
        # Real dock answer to GET_INDICATOR: 08 2d 01 00 ... 1f -> byte [2] = 1.
        rejected = bytes.fromhex('08 2d 01 00 00 00 00 00 00 00 00 00 00 00 00 00 1f'.replace(' ', ''))
        port = FakePort(replies=[rejected])
        with self.assertRaises(protocol.CommandRejected):
            DockClient(command_port=port).read_indicator()
        self.assertEqual(len(port.written), 1)

    def test_real_dock_light_answer_is_accepted(self):
        answer = bytes.fromhex('08 19 00 00 00 0a 04 ff ff ff 04 02 01 00 00 00 22'.replace(' ', ''))
        light = DockClient(command_port=FakePort(replies=[answer])).read_dock_light()
        self.assertEqual(light, protocol.DockLight(mode=4, red=255, green=255, blue=255, speed=5, brightness=3))


class ScreenClockClientTest(unittest.TestCase):
    def test_clock_uses_screen_report_length_and_id(self):
        port = FakePort(output_length=40, report_id=0x0A)
        moment = datetime.datetime(2026, 9, 19, 22, 45, 7)
        confirmed = DockClient(screen_port=port).sync_screen_clock(moment)
        self.assertEqual(port.written, [protocol.build_screen_clock(moment)])
        self.assertFalse(confirmed)

    def test_clock_reports_confirmation_when_dock_answers(self):
        port = FakePort(output_length=40, report_id=0x0A, replies=[bytes([0x0A, 0x00, 0x10]) + bytes(37)])
        confirmed = DockClient(screen_port=port).sync_screen_clock(datetime.datetime(2026, 1, 1))
        self.assertTrue(confirmed)

    def test_send_screen_returns_reply_and_records_traffic(self):
        answer = bytes([0x0A, 0x00, 0x10]) + bytes(37)
        port = FakePort(output_length=40, report_id=0x0A, replies=[answer])
        client = DockClient(screen_port=port)
        packet = bytes([0x0A]) + bytes(39)
        self.assertEqual(client.send_screen(packet), answer)
        self.assertEqual(client.last_screen_packet, packet)
        self.assertEqual(client.last_screen_response, answer)

    def test_clock_without_screen_channel_is_an_error(self):
        with self.assertRaises(RuntimeError):
            DockClient(command_port=FakePort()).sync_screen_clock(datetime.datetime(2026, 1, 1))


if __name__ == '__main__':
    unittest.main()
