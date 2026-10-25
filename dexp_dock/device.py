"""Connecting to the dock and describing what was found."""
import re

from .channels import VENDOR_ID, collection_number, select_channels
from .client import DockClient


def parse_color(text):
    m = re.fullmatch(r'#?([0-9a-fA-F]{6})', text.strip())
    if not m:
        raise ValueError('color must look like #RRGGBB, got %r' % text)
    value = int(m.group(1), 16)
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def diagnostics_report(interfaces, channels, tr, report_ids):
    ours = [i for i in interfaces if i.vendor_id == VENDOR_ID]
    lines = [tr('diag.interfaces', count=len(ours))]
    for i in sorted(ours, key=lambda x: (x.product_id, x.path)):
        rid = report_ids.get(i.path)
        lines.append('  PID %04X col %s  page %04X usage %04X  in %d out %d feat %d  id %s  %s' % (
            i.product_id, collection_number(i.path), i.usage_page, i.usage, i.input_length,
            i.output_length, i.feature_length, '-' if rid is None else '0x%02X' % rid, i.product))
        lines.append('    ' + i.path)
    none = tr('diag.none')
    lines.append(tr('diag.selected_command', path=channels.command.path if channels and channels.command else none))
    lines.append(tr('diag.selected_screen', path=channels.screen.path if channels and channels.screen else none))
    return '\n'.join(lines)


class DockConnection:
    """Open HID ports for the channels of the best matching dock."""

    def __init__(self, channels):
        from .hid_win import HidPort
        self.channels = channels
        self._ports = []
        command = self._open(HidPort, channels.command)
        screen = self._open(HidPort, channels.screen)
        self.client = DockClient(command_port=command, screen_port=screen)

    def _open(self, port_class, iface):
        if iface is None:
            return None
        port = port_class(iface)
        self._ports.append(port)
        return port

    @property
    def product_id(self):
        return self.channels.product_id

    @property
    def product(self):
        iface = self.channels.command or self.channels.screen
        return iface.product or 'DEXP'

    def close(self):
        for port in self._ports:
            port.close()
        self._ports = []


def find_dock(interfaces=None):
    """Return (DockConnection or None, interfaces) for the current USB state."""
    from . import hid_win
    if interfaces is None:
        interfaces = hid_win.enumerate_interfaces()
    channels = select_channels(interfaces)
    if channels is None:
        return None, interfaces
    return DockConnection(channels), interfaces


def report_ids():
    from . import hid_win
    return hid_win.known_report_ids()
