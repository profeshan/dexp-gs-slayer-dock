import datetime
import unittest

from dexp_dock import protocol
from dexp_dock.check import run_check
from dexp_dock.client import DockClient
from dexp_dock.i18n import Translator, load_locale
from tests.test_client import FakePort, reply


class RunCheckTest(unittest.TestCase):
    def setUp(self):
        self.tr = Translator(load_locale('en'))
        self.moment = datetime.datetime(2026, 9, 20, 12, 30, 0)

    def test_reports_raw_bytes_and_decoded_values(self):
        command = FakePort(replies=[
            reply(protocol.CMD_GET_DOCK_LIGHT, bytes([3, 255, 0, 0, 4, 9, 1]), length_byte=7),
            reply(protocol.CMD_GET_INDICATOR, bytes([2, 1, 4]), length_byte=3),
        ])
        screen = FakePort(output_length=40, report_id=0x0A, replies=[bytes([0x0A, 0x00, 0x10]) + bytes(37)])
        text = '\n'.join(run_check(DockClient(command_port=command, screen_port=screen), self.tr, self.moment))
        self.assertIn('08 19 00 00 00 07 03 ff', text)
        self.assertIn('#FF0000', text)
        self.assertIn('2 1 4', text)
        self.assertIn('0a 00 10 07 ea 09 14 0c 1e 00 07', text)
        self.assertIn('12:30', text)

    def test_silent_dock_is_reported_per_step_and_check_continues(self):
        command = FakePort(replies=[])
        screen = FakePort(output_length=40, report_id=0x0A, replies=[])
        lines = run_check(DockClient(command_port=command, screen_port=screen), self.tr, self.moment)
        text = '\n'.join(lines)
        self.assertEqual(text.count(self.tr('check.no_reply')), 3)
        self.assertEqual(len(screen.written), 1)


class BrokenPort(FakePort):
    def write(self, data):
        raise OSError(87, 'The parameter is incorrect')


class RunCheckUnsupportedTest(unittest.TestCase):
    def test_rejected_command_is_reported_as_unsupported(self):
        tr = Translator(load_locale('en'))
        rejected = bytes.fromhex('082d01000000000000000000000000001f')
        command = FakePort(replies=[
            reply(protocol.CMD_GET_DOCK_LIGHT, bytes([4, 255, 255, 255, 4, 2, 1])),
            rejected,
        ])
        lines = run_check(DockClient(command_port=command), tr, datetime.datetime(2026, 9, 20, 12, 30, 0))
        self.assertEqual(lines[1], tr('check.indicator', result=tr('check.unsupported')))


class RunCheckProgressTest(unittest.TestCase):
    def test_progress_is_announced_before_each_step(self):
        tr = Translator(load_locale('en'))
        events = []

        class RecordingPort(FakePort):
            def write(self, data):
                events.append('write %02x' % data[1 if data[0] == 0x08 else 2])
                super().write(data)

        client = DockClient(command_port=RecordingPort(), screen_port=RecordingPort(output_length=40, report_id=0x0A))
        run_check(client, tr, datetime.datetime(2026, 9, 20, 12, 30, 0), on_progress=events.append)
        progress = [e for e in events if not e.startswith('write')]
        self.assertEqual(len(progress), 3)
        self.assertLess(events.index(progress[0]), events.index('write 19'))
        self.assertLess(events.index(progress[2]), events.index('write 10'))


class RunCheckErrorsTest(unittest.TestCase):
    def test_os_errors_are_printed_and_every_step_still_runs(self):
        tr = Translator(load_locale('en'))
        client = DockClient(command_port=BrokenPort(), screen_port=BrokenPort(output_length=40, report_id=0x0A))
        lines = run_check(client, tr, datetime.datetime(2026, 9, 20, 12, 30, 0))
        text = '\n'.join(lines)
        self.assertEqual(text.count('The parameter is incorrect'), 3)
        self.assertIn('12:30', text)


if __name__ == '__main__':
    unittest.main()
