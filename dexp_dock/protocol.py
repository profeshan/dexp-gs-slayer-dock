"""Wire format of the DEXP GS Slayer Pro dock, recovered from the vendor HIDUsb.dll.

Command channel (dongle/dock, 17-byte output report):
    [0]     report id (0x08)
    [1]     command
    [2..4]  zero
    [5]     payload length for SET commands (0x0A), zero for GET commands
    [6..15] payload
    [16]    checksum = 0x55 - sum(bytes[0..15])
The dock answers with a report of the same shape that echoes the command in [1].

Screen channel (dock LCD, 40-byte output report):
    [0]     report id (0x0A)
    [2]     0x10 = set clock, followed by year (big endian), month, day,
            hour, minute, second, ISO weekday
    [-1]    checksum = 0x55 - sum(all previous bytes)
"""
from dataclasses import dataclass

COMMAND_REPORT_ID = 0x08
COMMAND_REPORT_LENGTH = 17
SET_PAYLOAD_LENGTH = 0x0A

CMD_SET_DOCK_LIGHT = 0x18
CMD_GET_DOCK_LIGHT = 0x19
CMD_SET_INDICATOR = 0x2C
CMD_GET_INDICATOR = 0x2D

SCREEN_REPORT_ID = 0x0A
SCREEN_REPORT_LENGTH = 40
SCREEN_CMD_SET_CLOCK = 0x10

LEVEL_MIN = 1
LEVEL_MAX = 10


class ProtocolError(Exception):
    pass


class CommandRejected(ProtocolError):
    """The dock answered with a non-zero status byte [2]: command not supported by this firmware."""


STATUS_OFFSET = 2


@dataclass(frozen=True)
class DockLight:
    """Decorative dock lighting. mode 0 turns the lighting off; speed/brightness are 1..10."""
    mode: int
    red: int
    green: int
    blue: int
    speed: int
    brightness: int


def checksum(data):
    return (0x55 - sum(data)) & 0xFF


def _require_byte(name, value):
    if not 0 <= value <= 0xFF:
        raise ValueError('%s must be 0..255, got %r' % (name, value))


def _require_level(name, value):
    if not LEVEL_MIN <= value <= LEVEL_MAX:
        raise ValueError('%s must be %d..%d, got %r' % (name, LEVEL_MIN, LEVEL_MAX, value))


def _command(cmd, payload=None):
    packet = bytearray(COMMAND_REPORT_LENGTH)
    packet[0] = COMMAND_REPORT_ID
    packet[1] = cmd
    if payload is not None:
        packet[5] = SET_PAYLOAD_LENGTH
        packet[6:6 + len(payload)] = payload
    packet[16] = checksum(packet[:16])
    return bytes(packet)


def is_valid_response(response, cmd):
    if len(response) < COMMAND_REPORT_LENGTH:
        return False
    return response[1] == cmd and response[16] == checksum(response[:16])


def _checked(response, cmd):
    if not is_valid_response(response, cmd):
        raise ProtocolError('unexpected response to command 0x%02X: %s' % (cmd, bytes(response).hex(' ')))
    return response


def build_set_dock_light(light):
    _require_byte('mode', light.mode)
    for name in ('red', 'green', 'blue'):
        _require_byte(name, getattr(light, name))
    _require_level('speed', light.speed)
    _require_level('brightness', light.brightness)
    payload = bytes([light.mode, light.red, light.green, light.blue,
                     light.speed - 1, light.brightness - 1])
    return _command(CMD_SET_DOCK_LIGHT, payload)


def build_get_dock_light():
    return _command(CMD_GET_DOCK_LIGHT)


def parse_dock_light(response):
    r = _checked(response, CMD_GET_DOCK_LIGHT)
    mode = r[6] if r[12] else 0
    return DockLight(mode=mode, red=r[7], green=r[8], blue=r[9],
                     speed=min(r[10] + 1, LEVEL_MAX), brightness=min(r[11] + 1, LEVEL_MAX))


def build_set_indicator(slots):
    if len(slots) != 3:
        raise ValueError('indicator needs exactly 3 slot values')
    for i, value in enumerate(slots):
        _require_byte('slot %d' % (i + 1), value)
    return _command(CMD_SET_INDICATOR, bytes(slots))


def build_get_indicator():
    return _command(CMD_GET_INDICATOR)


def parse_indicator(response):
    r = _checked(response, CMD_GET_INDICATOR)
    return tuple(r[6:9])


# --- Mouse DPI stage, read through the dongle (recovered from HIDUsb.dll, verified on the device) ---------
# The factory app first tells the dongle that a PC driver is running (UsbServer_SetPCDriverStatus: command 0x02,
# byte [5] = 1, byte [6] = 1 on start / 0 on exit). Only then does the dongle report the live mouse state:
# a read of config memory (command 0x08, address in [3:5], length in [5]) at address 4 returns the current DPI
# stage index in byte [6]. The dongle also sends unsolicited 0x0A reports whose byte [6] is a bit mask of what
# changed (bit 0 = DPI stage changed, bit 6 = battery level changed).
CMD_DRIVER_STATUS = 0x02
CMD_READ_CONFIG = 0x08
CMD_STATUS_EVENT = 0x0A
EVENT_DPI_CHANGED = 0x01
DPI_ADDRESS = 0x0004
MODE_FIXED_COLOR = 3

# Stage index -> colour of the mouse's own DPI indicator (manual: 800 red, 1600 green, 2400 blue,
# 3200 yellow, 5600 cyan, 26000 purple).
DPI_STAGE_COLORS = ('#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#00FFFF', '#FF00FF')


def build_set_driver_status(running):
    packet = bytearray(COMMAND_REPORT_LENGTH)
    packet[0] = COMMAND_REPORT_ID
    packet[1] = CMD_DRIVER_STATUS
    packet[5] = 1
    packet[6] = 1 if running else 0
    packet[16] = checksum(packet[:16])
    return bytes(packet)


def build_read_config(address, length=1):
    if not 0 <= address <= 0xFFFF:
        raise ValueError('address must be 0..65535, got %r' % address)
    if not 1 <= length <= 10:
        raise ValueError('length must be 1..10, got %r' % length)
    packet = bytearray(COMMAND_REPORT_LENGTH)
    packet[0] = COMMAND_REPORT_ID
    packet[1] = CMD_READ_CONFIG
    packet[3] = address >> 8
    packet[4] = address & 0xFF
    packet[5] = length
    packet[16] = checksum(packet[:16])
    return bytes(packet)


def is_config_answer(response, address):
    """True for the dongle's answer to build_read_config(address): same command, status 0, same address."""
    return (is_valid_response(response, CMD_READ_CONFIG) and response[STATUS_OFFSET] == 0
            and response[3] == address >> 8 and response[4] == address & 0xFF)


# --- DPI profile as stored in the mouse (seen in a memory dump and matched against the factory app's UI) ---
# Every field is stored with its own check byte (0x55 - sum of the field's bytes), so partial or torn reads are
# detectable. Layout of the first 0x4C bytes:
#   0x00  polling rate bit mask (+ check byte)     0x40 = 8000 Hz
#   0x02  number of DPI stages (+ check byte)
#   0x04  current stage index (+ check byte)
#   0x0C  8 stage entries of 4 bytes: x code, y code, flags, check; DPI = (code + 1) * 50
#   0x2C  8 colour entries of 4 bytes: R, G, B, check
# Stage i uses DPI entry i and colour entry i; only the first `count` stages are active.
EVENT_CONFIG_CHANGED = 0x04
EVENT_DPI_LED_CHANGED = 0x08
PROFILE_ADDRESS = 0x0000
PROFILE_LENGTH = 0x4C
STAGE_COUNT_OFFSET = 0x02
STAGE_DPI_OFFSET = 0x0C
STAGE_COLOR_OFFSET = 0x2C
STAGE_ENTRY_SIZE = 4
MAX_STAGES = 8


@dataclass(frozen=True)
class DpiProfile:
    count: int
    dpis: tuple      # DPI per stage (None where the entry is damaged)
    colors: tuple    # '#RRGGBB' per stage (None where the entry is damaged)


def _entry(raw, offset, size):
    """The `size - 1` data bytes at offset if their check byte matches, else None."""
    chunk = raw[offset:offset + size]
    if len(chunk) < size or chunk[-1] != checksum(chunk[:-1]):
        return None
    return chunk[:-1]


def parse_dpi_profile(raw):
    """Decode the first PROFILE_LENGTH bytes of config memory; None if the stage count is unreadable."""
    raw = bytes(raw)
    if len(raw) < PROFILE_LENGTH:
        return None
    count_entry = _entry(raw, STAGE_COUNT_OFFSET, 2)
    if count_entry is None or not 1 <= count_entry[0] <= MAX_STAGES:
        return None
    dpis, colors = [], []
    for i in range(count_entry[0]):
        dpi = _entry(raw, STAGE_DPI_OFFSET + i * STAGE_ENTRY_SIZE, STAGE_ENTRY_SIZE)
        color = _entry(raw, STAGE_COLOR_OFFSET + i * STAGE_ENTRY_SIZE, STAGE_ENTRY_SIZE)
        dpis.append(None if dpi is None else (dpi[0] + 1) * 50)
        colors.append(None if color is None else '#%02X%02X%02X' % tuple(color))
    return DpiProfile(count=count_entry[0], dpis=tuple(dpis), colors=tuple(colors))


# The vendor clock code is broken (it sends 1 byte), so the real layout is unknown.
# These candidates are tried on hardware by `screen-probe`; each only varies where the
# 0x10 command, the year and the checksum sit.
CLOCK_VARIANTS = (1, 2, 3, 4, 5, 6)


def _date_bytes(moment, one_byte_year=False):
    year = [moment.year - 2000] if one_byte_year else [(moment.year >> 8) & 0xFF, moment.year & 0xFF]
    return bytes(year + [moment.month, moment.day, moment.hour, moment.minute, moment.second,
                         moment.isoweekday()])


def build_screen_clock_variant(number, moment, length=SCREEN_REPORT_LENGTH, report_id=SCREEN_REPORT_ID):
    if number == 1:
        return build_screen_clock(moment, length, report_id)
    packet = bytearray(length)
    packet[0] = report_id
    if number in (2, 5, 6):
        packet[2] = SCREEN_CMD_SET_CLOCK
        data = _date_bytes(moment, one_byte_year=(number == 6))
        packet[3:3 + len(data)] = data
    elif number in (3, 4):
        packet[1] = SCREEN_CMD_SET_CLOCK
        data = _date_bytes(moment)
        packet[2:2 + len(data)] = data
    else:
        raise ValueError('unknown clock variant %r' % number)
    if number == 2:
        packet[11] = checksum(packet[:11])
    elif number == 4:
        packet[10] = checksum(packet[:10])
    elif number == 5:
        packet[-1] = checksum(packet[1:-1])
    else:
        packet[-1] = checksum(packet[:-1])
    return bytes(packet)


def variant_marker_time(number, base):
    """A time that reveals which variant the screen accepted: variant N shows 0N:1N on day N of January."""
    return base.replace(month=1, day=number, hour=number, minute=10 + number, second=0, microsecond=0)


def build_screen_clock(moment, length=SCREEN_REPORT_LENGTH, report_id=SCREEN_REPORT_ID):
    if length < 12:
        raise ValueError('screen report is too short: %d' % length)
    packet = bytearray(length)
    packet[0] = report_id
    packet[2] = SCREEN_CMD_SET_CLOCK
    packet[3] = (moment.year >> 8) & 0xFF
    packet[4] = moment.year & 0xFF
    packet[5] = moment.month
    packet[6] = moment.day
    packet[7] = moment.hour
    packet[8] = moment.minute
    packet[9] = moment.second
    packet[10] = moment.isoweekday()
    packet[-1] = checksum(packet[:-1])
    return bytes(packet)
