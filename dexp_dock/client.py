"""High-level dock operations on top of a report port (real HID or a test double).

A port provides: `output_length`, `report_id` (may be None), `write(bytes)`,
`read(timeout_ms) -> bytes | None` and `drain()`.
"""
import logging
import time

from . import protocol

logger = logging.getLogger(__name__)
MAX_REPORTS_PER_ATTEMPT = 500
ANSWER_WINDOW_FACTOR = 3


class DeviceTimeout(Exception):
    pass


class DockClient:
    def __init__(self, command_port=None, screen_port=None, attempts=2, timeout_ms=150):
        self.command_port = command_port
        self.screen_port = screen_port
        self.attempts = attempts
        self.timeout_ms = timeout_ms
        # Raw traffic of the latest exchange, kept for diagnostics.
        self.last_response = None
        self.last_screen_packet = None
        self.last_screen_response = None
        self.event_flags = 0

    @staticmethod
    def _fit(packet, port):
        length = port.output_length or len(packet)
        if length < len(packet):
            raise ValueError('report is %d bytes, packet needs %d' % (length, len(packet)))
        return packet + bytes(length - len(packet))

    def _transact(self, packet, cmd):
        port = self.command_port
        if port is None:
            raise RuntimeError('dock command channel is not available')
        data = self._fit(packet, port)
        self.last_response = None
        for _ in range(self.attempts):
            port.drain()
            port.write(data)
            # The dongle may interleave unrelated status reports, so wait by time, not by count.
            deadline = time.monotonic() + self.timeout_ms * ANSWER_WINDOW_FACTOR / 1000
            for _ in range(MAX_REPORTS_PER_ATTEMPT):
                response = port.read(self.timeout_ms)
                if response is None:
                    break
                if protocol.is_valid_response(response, cmd):
                    self.last_response = response
                    if response[protocol.STATUS_OFFSET]:
                        raise protocol.CommandRejected('command 0x%02X rejected with status %d' % (
                            cmd, response[protocol.STATUS_OFFSET]))
                    return response
                logger.debug('skipped report while waiting for 0x%02X: %s', cmd, bytes(response).hex(' '))
                if time.monotonic() > deadline:
                    break
        logger.warning('no answer to command 0x%02X', cmd)
        raise DeviceTimeout('no answer to command 0x%02X' % cmd)

    def read_dock_light(self):
        response = self._transact(protocol.build_get_dock_light(), protocol.CMD_GET_DOCK_LIGHT)
        return protocol.parse_dock_light(response)

    def set_dock_light(self, light):
        self._transact(protocol.build_set_dock_light(light), protocol.CMD_SET_DOCK_LIGHT)

    def read_indicator(self):
        response = self._transact(protocol.build_get_indicator(), protocol.CMD_GET_INDICATOR)
        return protocol.parse_indicator(response)

    def set_indicator(self, slots):
        self._transact(protocol.build_set_indicator(slots), protocol.CMD_SET_INDICATOR)

    def set_driver_status(self, running):
        """Tell the dongle a PC driver is running (what the factory app does on start/exit)."""
        self._transact(protocol.build_set_driver_status(running), protocol.CMD_DRIVER_STATUS)

    def _note_event(self, report):
        """Remember what the dongle's unsolicited status reports (command 0x0A) say has changed."""
        if (report is not None and len(report) >= protocol.COMMAND_REPORT_LENGTH
                and protocol.is_valid_response(report, protocol.CMD_STATUS_EVENT)):
            self.event_flags |= report[6]

    def take_event_flags(self):
        """Bit mask of changes reported since the last call (protocol.EVENT_*), then reset."""
        flags, self.event_flags = self.event_flags, 0
        return flags

    def _read_config_once(self, address, length, window):
        """One request/answer exchange; returns the bytes read or None. Events seen on the way are recorded."""
        port = self.command_port
        if port is None:
            raise RuntimeError('dock command channel is not available')
        for report in port.drain() or ():
            self._note_event(report)
        port.write(self._fit(protocol.build_read_config(address, length), port))
        deadline = time.monotonic() + window
        while time.monotonic() < deadline:
            response = port.read(self.timeout_ms)
            if response is None:
                continue
            self._note_event(response)
            if protocol.is_config_answer(response, address):
                self.last_response = response
                return bytes(response[6:6 + length])
        return None

    def poll_dpi_stage(self, window=0.45):
        """Current DPI stage index of the mouse, or None if no valid answer arrived within `window` seconds.

        Silence is normal here (the mouse may be asleep, the dongle needs a moment after the driver handshake),
        so unlike the other commands this never raises DeviceTimeout.
        """
        data = self._read_config_once(protocol.DPI_ADDRESS, 1, window)
        return None if data is None else data[0]

    def read_config_block(self, address, length, attempts=3, window=0.3):
        """Read `length` bytes of config memory in chunks of at most 10; None if a chunk never gets answered."""
        out = bytearray()
        for offset in range(0, length, 10):
            size = min(10, length - offset)
            for _ in range(attempts):
                chunk = self._read_config_once(address + offset, size, window)
                if chunk is not None:
                    out += chunk
                    break
            else:
                return None
        return bytes(out)

    def read_dpi_profile(self):
        """The mouse's DPI stages (count, DPI values, colours), or None if they could not be read cleanly."""
        raw = self.read_config_block(protocol.PROFILE_ADDRESS, protocol.PROFILE_LENGTH)
        return None if raw is None else protocol.parse_dpi_profile(raw)

    def _screen(self):
        if self.screen_port is None:
            raise RuntimeError('dock screen channel is not available')
        return self.screen_port

    def screen_report_shape(self):
        """(length, report id) of the screen output report."""
        port = self._screen()
        return (port.output_length or protocol.SCREEN_REPORT_LENGTH,
                port.report_id if port.report_id is not None else protocol.SCREEN_REPORT_ID)

    def send_screen(self, packet):
        """Write one report to the screen channel; returns the dock's reply or None."""
        port = self._screen()
        port.drain()
        port.write(packet)
        response = port.read(self.timeout_ms * 2)
        self.last_screen_packet = packet
        self.last_screen_response = response
        return response

    def sync_screen_clock(self, moment):
        """Send the clock to the dock screen. Returns True if the dock answered."""
        length, report_id = self.screen_report_shape()
        response = self.send_screen(protocol.build_screen_clock(moment, length=length, report_id=report_id))
        return response is not None and len(response) > 2 and response[2] == protocol.SCREEN_CMD_SET_CLOCK
