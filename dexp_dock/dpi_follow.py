"""Dock backlight follows the mouse's current DPI stage, using the colours of the mouse's own DPI profile.

The dongle only reports the live mouse state after the factory app's own handshake ("a PC driver is running"),
see protocol.py. While active, the backlight is a fixed colour equal to the colour the factory app shows for the
current stage; the stage list (count, DPI, colours) is read from the mouse and re-read whenever it changes, so
edits made in GS_Slayer Pro show up on the dock at once. On stop the backlight the dock had before is written
back.

Sharing the dongle with a running GS_Slayer Pro: the factory app can switch "driver running" off when its window
is hidden, which freezes the live data; that is detected (a DPI-changed event with an unchanged reading) and the
handshake is repeated. When the factory app is still running at exit the dongle is left in driver mode instead
of being switched off under it.
"""
import logging
import subprocess
import sys
import time

from . import protocol
from .client import DeviceTimeout
from .device import parse_color

logger = logging.getLogger(__name__)

# A reading must repeat this many times in a row before the backlight changes. The dongle sometimes echoes the
# request instead of answering (an echo looks like stage 0), so a single reading is not trusted.
STABLE_READINGS = 2
FALLBACK_COLOR = '#FFFFFF'
STALE_CHECK_SECONDS = 1.5
HANDSHAKE_MIN_INTERVAL_SECONDS = 10.0
PROFILE_REFRESH_SECONDS = 30.0
PROFILE_RETRY_SECONDS = 2.0
PROFILE_WAIT_SECONDS = 3.0   # show the fallback colour only if the profile is still unreadable after this long
PROFILE_EVENTS = protocol.EVENT_CONFIG_CHANGED | protocol.EVENT_DPI_LED_CHANGED
FACTORY_APP = 'GS_Slayer Pro.exe'


def stage_color(stage, colors=protocol.DPI_STAGE_COLORS):
    return colors[stage] if 0 <= stage < len(colors) and colors[stage] else FALLBACK_COLOR


def factory_app_running():
    """True if the vendor GS_Slayer Pro process is running (so it may rely on the dongle's driver mode)."""
    if sys.platform != 'win32':
        return False
    try:
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq %s' % FACTORY_APP, '/NH', '/FO', 'CSV'],
                                capture_output=True, text=True, timeout=5,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return FACTORY_APP.lower() in result.stdout.lower()


class DpiFollower:
    """`get_client` returns the current DockClient (it changes when the dock is re-plugged).

    `colors` is only the fallback table, used until (or unless) the mouse's own stage colours can be read.
    """

    def __init__(self, get_client, colors=protocol.DPI_STAGE_COLORS, speed=5, brightness=10,
                 clock=time.monotonic):
        self._get_client = get_client
        self.colors = tuple(colors)
        self.speed = speed
        self.brightness = brightness
        self._clock = clock
        self.saved = None      # backlight the dock had before we took over
        self.profile = None    # protocol.DpiProfile read from the mouse
        self.stage = None      # stage whose colour is currently shown
        self.shown_color = None
        self.running = False
        self._candidate = None
        self._repeats = 0
        self._handshake_at = 0.0
        self._profile_at = 0.0
        self._retry_at = 0.0
        self._give_up_at = 0.0
        self._last_reading = None
        self._stale_check = None  # (time of a DPI-changed event, reading before it)

    # ---- lifecycle ----------------------------------------------------

    def start(self):
        """Remember the current backlight and switch the dongle into driver mode."""
        client = self._get_client()
        if self.saved is None:
            self.saved = client.read_dock_light()
        client.set_driver_status(True)
        self.running = True
        self._begin_session()
        logger.info('dpi follow started, saved backlight %s', self.saved)

    def handshake(self):
        """Repeat the driver handshake after the dock was re-plugged and show the colour again."""
        self._get_client().set_driver_status(True)
        self._begin_session()

    def _begin_session(self):
        now = self._clock()
        self._handshake_at = now
        self._give_up_at = now + PROFILE_WAIT_SECONDS
        self._profile_at = self._retry_at = 0.0
        self._last_reading = self._stale_check = None
        self.profile = None
        self.stage = self.shown_color = None
        self._reset_reading()

    def stop(self):
        """Put the previous backlight back and, unless the factory app runs, leave driver mode. Safe twice."""
        if not self.running:
            return
        self.running = False
        saved, self.saved = self.saved, None
        self.stage = self.shown_color = self.profile = None
        self._reset_reading()
        try:
            client = self._get_client()
        except RuntimeError:
            return  # dock is gone, nothing to restore
        try:
            if saved is not None:
                client.set_dock_light(saved)
        finally:
            if factory_app_running():
                logger.info('factory app is running, leaving the dongle in driver mode')
            else:
                client.set_driver_status(False)
        logger.info('dpi follow stopped, backlight restored')

    # ---- one polling step ---------------------------------------------

    def poll(self):
        """One step. Returns the stage whose colour is shown now, or None while the mouse has not answered."""
        client = self._get_client()
        now = self._clock()
        reading = client.poll_dpi_stage()
        events = client.take_event_flags()
        if events & protocol.EVENT_DPI_CHANGED:
            self._stale_check = (now, self._last_reading)
        if reading is None:
            return self.stage  # the dongle is not answering yet, so reading the profile would only stall
        self._check_for_stale_data(client, now, reading)
        self._last_reading = reading
        self._refresh_profile(client, now, forced=bool(events & PROFILE_EVENTS))
        if reading == self._candidate:
            self._repeats += 1
        else:
            self._candidate, self._repeats = reading, 1
        if self._repeats >= STABLE_READINGS and (self.profile is not None or now >= self._give_up_at):
            self._show(client, reading)
        return self.stage

    def _check_for_stale_data(self, client, now, reading):
        """The dongle serves cached values once the driver mode is switched off (the factory app does that when
        its window is hidden). Symptom: a "DPI changed" event but the same stage keeps coming back. Repeat the
        handshake then, but not on a timer: every repeat makes the dongle resync for a few seconds."""
        if self._stale_check is None:
            return
        since, before = self._stale_check
        if before is None or reading != before:
            self._stale_check = None  # the value moved: the data is live
        elif now - since >= STALE_CHECK_SECONDS and now - self._handshake_at >= HANDSHAKE_MIN_INTERVAL_SECONDS:
            self._stale_check = None
            self._handshake_at = now
            logger.info('dpi stage did not follow a change event: repeating the driver handshake')
            try:
                client.set_driver_status(True)
            except (DeviceTimeout, protocol.CommandRejected):
                logger.info('driver handshake repeat was not answered')

    def _refresh_profile(self, client, now, forced):
        due = (forced or now - self._profile_at >= PROFILE_REFRESH_SECONDS
               or (self.profile is None and now >= self._retry_at))
        if not due:
            return
        profile = client.read_dpi_profile()
        if profile is None:
            # keep what we have and try again shortly (both the "never read" and the periodic trigger)
            self._retry_at = now + PROFILE_RETRY_SECONDS
            self._profile_at = now - PROFILE_REFRESH_SECONDS + PROFILE_RETRY_SECONDS
            return
        self._profile_at = now
        if profile != self.profile:
            logger.info('dpi profile: %d stages, dpi %s, colours %s', profile.count, profile.dpis, profile.colors)
        self.profile = profile
        if self.stage is not None:
            self._show(client, self.stage)  # the colours may have changed under the stage that is shown

    def _show(self, client, stage):
        color = self.color_for(stage)
        if stage == self.stage and color == self.shown_color:
            return
        client.set_dock_light(self.light_for(stage))
        self.stage, self.shown_color = stage, color
        logger.info('dpi stage %d -> backlight %s', stage, color)

    # ---- colours ------------------------------------------------------

    def color_for(self, stage):
        """The colour the factory app shows for this stage: from the mouse, else from the fallback table."""
        if self.profile is not None and 0 <= stage < len(self.profile.colors) and self.profile.colors[stage]:
            return self.profile.colors[stage]
        return stage_color(stage, self.colors)

    def light_for(self, stage):
        red, green, blue = parse_color(self.color_for(stage))
        return protocol.DockLight(mode=protocol.MODE_FIXED_COLOR, red=red, green=green, blue=blue,
                                  speed=self.speed, brightness=self.brightness)

    @property
    def stage_count(self):
        return self.profile.count if self.profile is not None else len(self.colors)

    @property
    def stage_dpi(self):
        if self.profile is not None and self.stage is not None and self.stage < len(self.profile.dpis):
            return self.profile.dpis[self.stage]
        return None

    def _reset_reading(self):
        self._candidate, self._repeats = None, 0
