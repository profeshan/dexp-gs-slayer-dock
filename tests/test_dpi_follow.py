import unittest
from unittest import mock

from dexp_dock import dpi_follow, protocol
from dexp_dock.client import DockClient
from dexp_dock.dpi_follow import DpiFollower, stage_color


def bytes_from_hex(text):
    return bytes.fromhex(text.replace(' ', '').replace('\n', ''))


# First 0x4C bytes of the configuration memory read from the real mouse while GS_Slayer Pro showed
# two DPI levels: 800 (red) and 2500 (yellow).
REAL_PROFILE_RAW = bytes_from_hex('''
    40 15 02 53 01 54 00 55 00 55 02 53 0f 0f 00 37
    31 31 00 f3 1f 1f 00 17 2f 2f 00 f7 07 07 88 bf
    6f 6f 00 77 2b 2b 45 ba 2b 2b 45 ba ff 00 00 56
    ff ff 00 57 00 ff 00 56 00 00 ff 56 ff 00 ff 57
    00 ff ff 57 00 ff ff 57 ff ff ff 58''')
REAL_PROFILE = protocol.DpiProfile(count=2, dpis=(800, 2500), colors=('#FF0000', '#FFFF00'))


def with_check(*data):
    return bytes(data) + bytes([protocol.checksum(bytes(data))])


def report(cmd, payload=b'', status=0, address=0, length_byte=0x0A):
    body = bytearray(17)
    body[0] = 0x08
    body[1] = cmd
    body[2] = status
    body[3] = address >> 8
    body[4] = address & 0xFF
    body[5] = length_byte
    body[6:6 + len(payload)] = payload
    body[16] = protocol.checksum(body[:16])
    return bytes(body)


def config_answer(stage, address=protocol.DPI_ADDRESS, status=0):
    return report(protocol.CMD_READ_CONFIG, bytes([stage]), status=status, address=address, length_byte=1)


def status_event(flags):
    return report(protocol.CMD_STATUS_EVENT, bytes([flags]))


class FakePort:
    def __init__(self, replies=None):
        self.output_length = 17
        self.report_id = None
        self.written = []
        self.replies = list(replies or [])

    def write(self, data):
        self.written.append(bytes(data))

    def read(self, timeout_ms):
        return self.replies.pop(0) if self.replies else None

    def drain(self):
        return []


class MemoryPort(FakePort):
    """Answers config reads from a bytes image, like the dongle does."""

    def __init__(self, memory, pending_events=()):
        super().__init__()
        self.memory = memory
        self.queue = list(pending_events)

    def write(self, data):
        super().write(data)
        address = data[3] << 8 | data[4]
        length = data[5]
        self.queue.append(report(protocol.CMD_READ_CONFIG, self.memory[address:address + length], address=address,
                                 length_byte=length))

    def read(self, timeout_ms):
        return self.queue.pop(0) if self.queue else None


class DpiPacketTest(unittest.TestCase):
    def test_driver_status_packets_match_the_ones_the_dongle_accepted(self):
        # Captured from the real dongle: it answered both with an identical echo and status 0.
        self.assertEqual(protocol.build_set_driver_status(True),
                         bytes_from_hex('08 02 00 00 00 01 01 00 00 00 00 00 00 00 00 00 49'))
        self.assertEqual(protocol.build_set_driver_status(False),
                         bytes_from_hex('08 02 00 00 00 01 00 00 00 00 00 00 00 00 00 00 4a'))

    def test_read_dpi_request_matches_the_vendor_packet(self):
        self.assertEqual(protocol.build_read_config(protocol.DPI_ADDRESS),
                         bytes_from_hex('08 08 00 00 04 01 00 00 00 00 00 00 00 00 00 00 40'))

    def test_read_config_validates_arguments(self):
        with self.assertRaises(ValueError):
            protocol.build_read_config(0x10000)
        with self.assertRaises(ValueError):
            protocol.build_read_config(4, 11)

    def test_real_answer_is_recognised(self):
        answer = bytes_from_hex('08 08 00 00 04 01 03 00 00 00 00 00 00 00 00 00 3d')
        self.assertTrue(protocol.is_config_answer(answer, protocol.DPI_ADDRESS))

    def test_refusal_wrong_address_and_other_commands_are_not_answers(self):
        refusal = bytes_from_hex('08 08 01 00 04 81 00 00 00 00 00 00 00 00 00 00 bf')
        self.assertFalse(protocol.is_config_answer(refusal, protocol.DPI_ADDRESS))
        self.assertFalse(protocol.is_config_answer(config_answer(2, address=0), protocol.DPI_ADDRESS))
        self.assertFalse(protocol.is_config_answer(status_event(1), protocol.DPI_ADDRESS))


class ProfileParseTest(unittest.TestCase):
    def test_real_memory_dump_decodes_to_what_the_factory_app_shows(self):
        self.assertEqual(protocol.parse_dpi_profile(REAL_PROFILE_RAW), REAL_PROFILE)

    def test_stage_count_selects_how_many_entries_are_active(self):
        raw = bytearray(REAL_PROFILE_RAW)
        raw[2:4] = with_check(4)
        profile = protocol.parse_dpi_profile(bytes(raw))
        self.assertEqual(profile.count, 4)
        self.assertEqual(profile.dpis, (800, 2500, 1600, 2400))
        self.assertEqual(profile.colors, ('#FF0000', '#FFFF00', '#00FF00', '#0000FF'))

    def test_damaged_entry_becomes_none_but_the_rest_survives(self):
        raw = bytearray(REAL_PROFILE_RAW)
        raw[protocol.STAGE_COLOR_OFFSET + 4] ^= 0x01  # break the second colour entry
        profile = protocol.parse_dpi_profile(bytes(raw))
        self.assertEqual(profile.colors, ('#FF0000', None))
        self.assertEqual(profile.dpis, (800, 2500))

    def test_unreadable_stage_count_gives_no_profile(self):
        raw = bytearray(REAL_PROFILE_RAW)
        raw[3] ^= 0xFF
        self.assertIsNone(protocol.parse_dpi_profile(bytes(raw)))
        self.assertIsNone(protocol.parse_dpi_profile(REAL_PROFILE_RAW[:10]))


class DpiClientTest(unittest.TestCase):
    def test_poll_returns_stage_and_notes_status_events(self):
        port = FakePort(replies=[status_event(protocol.EVENT_DPI_CHANGED), config_answer(4)])
        client = DockClient(command_port=port)
        self.assertEqual(client.poll_dpi_stage(), 4)
        self.assertEqual(port.written, [protocol.build_read_config(protocol.DPI_ADDRESS)])
        self.assertEqual(client.take_event_flags(), protocol.EVENT_DPI_CHANGED)
        self.assertEqual(client.take_event_flags(), 0)

    def test_events_queued_before_the_request_are_not_lost(self):
        port = FakePort(replies=[config_answer(1)])
        port.drain = lambda: [status_event(protocol.EVENT_CONFIG_CHANGED)]
        client = DockClient(command_port=port)
        client.poll_dpi_stage()
        self.assertEqual(client.take_event_flags(), protocol.EVENT_CONFIG_CHANGED)

    def test_poll_returns_none_on_silence_instead_of_raising(self):
        client = DockClient(command_port=FakePort())
        self.assertIsNone(client.poll_dpi_stage(window=0.05))

    def test_driver_status_accepts_the_echo(self):
        port = FakePort(replies=[protocol.build_set_driver_status(True)])
        DockClient(command_port=port).set_driver_status(True)
        self.assertEqual(port.written, [protocol.build_set_driver_status(True)])

    def test_driver_status_refusal_is_reported(self):
        refusal = bytearray(protocol.build_set_driver_status(True))
        refusal[2] = 1
        refusal[16] = protocol.checksum(refusal[:16])
        with self.assertRaises(protocol.CommandRejected):
            DockClient(command_port=FakePort(replies=[bytes(refusal)])).set_driver_status(True)

    def test_profile_is_read_in_chunks_of_at_most_ten_bytes(self):
        port = MemoryPort(REAL_PROFILE_RAW + bytes(16))
        profile = DockClient(command_port=port).read_dpi_profile()
        self.assertEqual(profile, REAL_PROFILE)
        self.assertTrue(all(len(p) == 17 for p in port.written))
        self.assertEqual([p[5] for p in port.written], [10] * 7 + [6])
        self.assertEqual([p[3] << 8 | p[4] for p in port.written], list(range(0, 0x4C, 10)))

    def test_profile_read_gives_up_when_the_dongle_stays_silent(self):
        client = DockClient(command_port=FakePort())
        self.assertIsNone(client.read_config_block(0, 20, attempts=1, window=0.02))


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeClient:
    def __init__(self, readings, saved, profile=REAL_PROFILE, events=()):
        self.readings = list(readings)
        self.saved = saved
        self.profile = profile
        self.events = list(events)
        self.lights = []
        self.status_calls = []
        self.profile_reads = 0

    def read_dock_light(self):
        return self.saved

    def set_dock_light(self, light):
        self.lights.append(light)

    def set_driver_status(self, running):
        self.status_calls.append(running)

    def poll_dpi_stage(self):
        return self.readings.pop(0) if self.readings else None

    def take_event_flags(self):
        return self.events.pop(0) if self.events else 0

    def read_dpi_profile(self):
        self.profile_reads += 1
        return self.profile


NEON = protocol.DockLight(mode=4, red=255, green=255, blue=0, speed=3, brightness=2)


def rgb(light):
    return light.red, light.green, light.blue


class FollowerTest(unittest.TestCase):
    def make(self, readings, **kwargs):
        client = FakeClient(readings, NEON, **kwargs)
        self.clock = FakeClock()
        return DpiFollower(lambda: client, speed=5, brightness=10, clock=self.clock), client

    def test_fallback_colours_follow_the_manual(self):
        self.assertEqual([stage_color(i) for i in range(6)],
                         ['#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#00FFFF', '#FF00FF'])
        self.assertEqual(stage_color(9), '#FFFFFF')

    def test_start_remembers_backlight_and_enters_driver_mode(self):
        follower, client = self.make([])
        follower.start()
        self.assertEqual(follower.saved, NEON)
        self.assertEqual(client.status_calls, [True])

    def test_colour_comes_from_the_mouse_profile_after_stable_readings(self):
        follower, client = self.make([1, 1])
        follower.start()
        self.assertIsNone(follower.poll())
        self.assertEqual(client.lights, [])
        self.assertEqual(follower.poll(), 1)
        # stage 1 of the user's profile is yellow (the manual's table would say green)
        self.assertEqual(client.lights, [protocol.DockLight(mode=3, red=255, green=255, blue=0, speed=5, brightness=10)])
        self.assertEqual(client.profile_reads, 1)
        self.assertEqual(follower.stage_count, 2)
        self.assertEqual(follower.stage_dpi, 2500)

    def test_waits_for_the_profile_before_falling_back_to_the_table(self):
        follower, client = self.make([1, 1, 1], profile=None)
        follower.start()
        follower.poll()
        follower.poll()
        self.assertEqual(client.lights, [])          # still hoping to read the profile
        self.clock.advance(dpi_follow.PROFILE_WAIT_SECONDS + 0.5)
        follower.poll()
        self.assertEqual([rgb(l) for l in client.lights], [(0, 255, 0)])  # fallback: manual's green for stage 1

    def test_profile_is_not_read_while_the_dongle_is_silent(self):
        follower, client = self.make([])
        follower.start()
        for _ in range(3):
            follower.poll()
        self.assertEqual(client.profile_reads, 0)

    def test_profile_change_event_recolours_the_shown_stage(self):
        follower, client = self.make([0, 0, 0], events=[0, 0, protocol.EVENT_DPI_LED_CHANGED])
        follower.start()
        follower.poll()
        follower.poll()
        self.assertEqual([rgb(l) for l in client.lights], [(255, 0, 0)])
        client.profile = protocol.DpiProfile(count=2, dpis=(800, 2500), colors=('#00FF00', '#FFFF00'))
        follower.poll()
        self.assertEqual([rgb(l) for l in client.lights], [(255, 0, 0), (0, 255, 0)])
        self.assertEqual(client.profile_reads, 2)

    def test_single_echo_like_reading_is_ignored(self):
        follower, client = self.make([1, 1, 0, 1, 1])
        follower.start()
        for _ in range(5):
            follower.poll()
        self.assertEqual(len(client.lights), 1)  # yellow applied once; the lone 0 never reached the dock

    def test_new_stage_rewrites_the_colour(self):
        follower, client = self.make([0, 0, 1, 1])
        follower.start()
        for _ in range(4):
            follower.poll()
        self.assertEqual([rgb(l) for l in client.lights], [(255, 0, 0), (255, 255, 0)])

    def test_silence_keeps_the_current_colour(self):
        follower, client = self.make([1, 1])
        follower.start()
        follower.poll()
        follower.poll()
        self.assertEqual(follower.poll(), 1)
        self.assertEqual(len(client.lights), 1)

    def test_handshake_is_not_repeated_on_a_timer(self):
        follower, client = self.make([1, 1, 1])
        follower.start()
        for _ in range(3):
            self.clock.advance(5)
            follower.poll()
        self.assertEqual(client.status_calls, [True])

    def test_frozen_reading_after_a_change_event_repeats_the_handshake(self):
        # the dongle serves cached values when the driver mode was switched off (e.g. by the factory app)
        follower, client = self.make([1, 1, 1, 1], events=[0, 0, protocol.EVENT_DPI_CHANGED, 0])
        follower.start()
        for _ in range(3):
            follower.poll()
        self.clock.advance(dpi_follow.HANDSHAKE_MIN_INTERVAL_SECONDS + 1)
        follower.poll()
        self.assertEqual(client.status_calls, [True, True])

    def test_reading_that_follows_a_change_event_means_the_data_is_live(self):
        follower, client = self.make([1, 1, 0], events=[0, 0, protocol.EVENT_DPI_CHANGED])
        follower.start()
        for _ in range(3):
            follower.poll()
        self.clock.advance(dpi_follow.HANDSHAKE_MIN_INTERVAL_SECONDS + 1)
        follower.poll()
        self.assertEqual(client.status_calls, [True])

    def test_stop_restores_backlight_and_leaves_driver_mode_once(self):
        follower, client = self.make([0, 0])
        follower.start()
        follower.poll()
        follower.poll()
        with mock.patch.object(dpi_follow, 'factory_app_running', return_value=False):
            follower.stop()
            follower.stop()  # second call changes nothing
        self.assertEqual(client.lights[-1], NEON)
        self.assertEqual(len(client.lights), 2)
        self.assertEqual(client.status_calls, [True, False])

    def test_stop_keeps_driver_mode_while_the_factory_app_runs(self):
        follower, client = self.make([0, 0])
        follower.start()
        follower.poll()
        follower.poll()
        with mock.patch.object(dpi_follow, 'factory_app_running', return_value=True):
            follower.stop()
        self.assertEqual(client.lights[-1], NEON)
        self.assertEqual(client.status_calls, [True])

    def test_handshake_after_replug_shows_the_colour_again(self):
        follower, client = self.make([1, 1, 1, 1])
        follower.start()
        follower.poll()
        follower.poll()
        follower.handshake()
        follower.poll()
        follower.poll()
        self.assertEqual(len(client.lights), 2)
        self.assertEqual(client.status_calls, [True, True])
        self.assertEqual(client.profile_reads, 2)


if __name__ == '__main__':
    unittest.main()
