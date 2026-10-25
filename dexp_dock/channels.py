"""Pick the dock's HID collections out of everything Windows enumerates.

The vendor app opens `vid_3554&pid_XXXX&mi_01&col05` for 17-byte commands and
`mi_01&col08` for the 40-byte screen reports. Collection numbers are matched first,
report lengths are the fallback in case a firmware revision reorders collections.
"""
import re
from dataclasses import dataclass
from typing import Optional

from . import protocol

VENDOR_ID = 0x3554
# Wireless dongle/dock PIDs from the vendor configs; the wired mouse is 0xFB36.
DOCK_PRODUCT_IDS = (0xFB34, 0xFB35)
COMMAND_COLLECTION = 5
SCREEN_COLLECTION = 8
VENDOR_USAGE_PAGE_MIN = 0xFF00


@dataclass(frozen=True)
class HidInterface:
    path: str
    vendor_id: int
    product_id: int
    usage_page: int
    usage: int
    input_length: int
    output_length: int
    feature_length: int
    product: str


@dataclass(frozen=True)
class DockChannels:
    command: Optional[HidInterface]
    screen: Optional[HidInterface]

    @property
    def product_id(self):
        return (self.command or self.screen).product_id


def collection_number(path):
    m = re.search(r'&col([0-9a-f]{2})', path, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _pick(candidates, collection, length):
    for c in candidates:
        if collection_number(c.path) == collection and c.output_length >= length:
            return c
    for c in candidates:
        if c.output_length == length:
            return c
    return None


def select_channels(interfaces):
    vendor = [i for i in interfaces
              if i.vendor_id == VENDOR_ID and i.usage_page >= VENDOR_USAGE_PAGE_MIN]
    by_product = {}
    for i in vendor:
        by_product.setdefault(i.product_id, []).append(i)

    options = []
    for pid, group in by_product.items():
        command = _pick(group, COMMAND_COLLECTION, protocol.COMMAND_REPORT_LENGTH)
        screen = _pick(group, SCREEN_COLLECTION, protocol.SCREEN_REPORT_LENGTH)
        if command is None and screen is None:
            continue
        rank = (screen is not None, pid in DOCK_PRODUCT_IDS, command is not None)
        options.append((rank, DockChannels(command=command, screen=screen)))
    if not options:
        return None
    options.sort(key=lambda o: o[0], reverse=True)
    return options[0][1]
