"""Tkinter window. All USB work runs on one background thread, results come back via a queue."""
import datetime
import json
import logging
import os
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, ttk

from . import device, protocol
from .client import DeviceTimeout
from .dpi_follow import DpiFollower, stage_color

logger = logging.getLogger(__name__)

PROBE_INTERVAL_MS = 3000
TRAY_POLL_MS = 300
TRAY_INACTIVE_COLOR = '#808080'
DPI_POLL_MS = 150
CLOSE_WAIT_SECONDS = 2.5
HEX_COLOR = re.compile(r'#[0-9a-fA-F]{6}')
AUTO_SYNC_SECONDS = 60
MODE_COUNT = 7
INDICATOR_OPTIONS = 5
PRESET_COLORS = ('#FF0000', '#FF8000', '#FFFF00', '#00FF00', '#00FFFF', '#0000FF', '#8000FF', '#FFFFFF')
SETTINGS_PATH = Path(os.environ.get('APPDATA', Path.home())) / 'dexp-dock' / 'settings.json'


def load_settings():
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(settings), encoding='utf-8')
    except OSError:
        pass


class DeviceWorker(threading.Thread):
    """Runs jobs against the dock one at a time; owns the connection."""

    def __init__(self, results):
        super().__init__(daemon=True)
        self.jobs = queue.Queue()
        self.results = results
        self.connection = None
        self.interfaces = []

    def submit(self, job, on_done=None):
        self.jobs.put((job, on_done))

    def run(self):
        while True:
            job, on_done = self.jobs.get()
            try:
                value, error = job(self), None
            except Exception as exc:  # the worker must outlive any single failed job
                value, error = None, exc
                if isinstance(exc, (OSError, DeviceTimeout)):
                    self.drop()
            if on_done is not None:
                self.results.put((on_done, value, error))

    def drop(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def require(self):
        if self.connection is None:
            raise RuntimeError('not connected')
        return self.connection.client


def probe(worker):
    """Find the dock or confirm it is still plugged in. Returns (connection_changed, connection)."""
    from . import hid_win
    interfaces = hid_win.enumerate_interfaces()
    worker.interfaces = interfaces
    if worker.connection is not None:
        paths = {i.path for i in interfaces}
        channels = worker.connection.channels
        alive = [c for c in (channels.command, channels.screen) if c is not None]
        if all(c.path in paths for c in alive):
            return False, worker.connection
        worker.drop()
        return True, None
    connection, _ = device.find_dock(interfaces)
    worker.connection = connection
    return connection is not None, connection


class App:
    def __init__(self, root, tr, tray=False, start_hidden=False):
        self.root = root
        self.tr = tr
        self.tray = None
        self._tray_pushed = None
        self._autostart_enabled = False
        self.settings = load_settings()
        self.results = queue.Queue()
        self.worker = DeviceWorker(self.results)
        self.worker.start()
        self.connected = False
        self.has_screen = False
        self.probed = False
        self.last_sync = 0.0
        self.following = False       # DPI-colour mode is on (a start job was submitted)
        self._poll_busy = False
        self._next_follow_try = 0.0
        self.follower = DpiFollower(self.worker.require, colors=self._dpi_colors())

        root.title(tr('app.title'))
        root.protocol('WM_DELETE_WINDOW', self._on_close)
        root.minsize(560, 420)
        notebook = ttk.Notebook(root)
        notebook.pack(fill='both', expand=True, padx=8, pady=(8, 0))
        self._build_screen_tab(notebook)
        self._build_light_tab(notebook)
        self._build_indicator_tab(notebook)
        self._build_diag_tab(notebook)
        self.status = tk.StringVar(value=tr('status.searching'))
        ttk.Label(root, textvariable=self.status, anchor='w').pack(fill='x', padx=10, pady=6)

        self._poll_results()
        self._tick_clock()
        self._probe()
        self.root.after(DPI_POLL_MS, self._dpi_tick)
        if tray:
            self._start_tray(start_hidden)

    # ---- layout -------------------------------------------------------

    def _build_screen_tab(self, notebook):
        tab = ttk.Frame(notebook, padding=12)
        notebook.add(tab, text=self.tr('tab.screen'))
        self.pc_time = tk.StringVar()
        ttk.Label(tab, textvariable=self.pc_time, font=('Segoe UI', 14)).pack(anchor='w')
        self.sync_button = ttk.Button(tab, text=self.tr('screen.sync_now'), command=self.sync_clock)
        self.sync_button.pack(anchor='w', pady=(12, 4))
        self.auto_sync = tk.BooleanVar(value=self.settings.get('auto_sync', True))
        ttk.Checkbutton(tab, text=self.tr('screen.auto_sync'), variable=self.auto_sync,
                        command=self._save_auto_sync).pack(anchor='w', pady=4)
        self.screen_result = tk.StringVar()
        ttk.Label(tab, textvariable=self.screen_result, foreground='#2a7a2a').pack(anchor='w', pady=4)
        ttk.Label(tab, text=self.tr('screen.note'), wraplength=500, foreground='#666666',
                  justify='left').pack(anchor='w', pady=(16, 0))

    def _build_light_tab(self, notebook):
        tab = ttk.Frame(notebook, padding=12)
        notebook.add(tab, text=self.tr('tab.light'))
        tab.columnconfigure(1, weight=1)

        ttk.Label(tab, text=self.tr('light.mode')).grid(row=0, column=0, sticky='w', pady=4)
        self.mode_names = [self.tr('light.mode.%d' % i) for i in range(MODE_COUNT)]
        self.mode = ttk.Combobox(tab, values=self.mode_names, state='readonly', width=28)
        self.mode.current(3)
        self.mode.grid(row=0, column=1, sticky='w', pady=4)

        ttk.Label(tab, text=self.tr('light.color')).grid(row=1, column=0, sticky='w', pady=4)
        color_row = ttk.Frame(tab)
        color_row.grid(row=1, column=1, sticky='w', pady=4)
        self.color = '#FF0000'
        self.swatch = tk.Label(color_row, width=6, background=self.color, relief='groove')
        self.swatch.pack(side='left')
        ttk.Button(color_row, text=self.tr('light.pick_color'), command=self._pick_color).pack(side='left', padx=8)

        ttk.Label(tab, text=self.tr('light.presets')).grid(row=2, column=0, sticky='w', pady=4)
        presets = ttk.Frame(tab)
        presets.grid(row=2, column=1, sticky='w', pady=4)
        for value in PRESET_COLORS:
            tk.Button(presets, background=value, activebackground=value, width=2, relief='flat',
                      command=lambda v=value: self._set_color(v)).pack(side='left', padx=2)

        self.brightness = tk.IntVar(value=10)
        self.speed = tk.IntVar(value=5)
        for row, key, var in ((3, 'light.brightness', self.brightness), (4, 'light.speed', self.speed)):
            ttk.Label(tab, text=self.tr(key)).grid(row=row, column=0, sticky='w', pady=4)
            line = ttk.Frame(tab)
            line.grid(row=row, column=1, sticky='we', pady=4)
            tk.Scale(line, from_=protocol.LEVEL_MIN, to=protocol.LEVEL_MAX, orient='horizontal',
                     variable=var, showvalue=True, length=260).pack(side='left')

        buttons = ttk.Frame(tab)
        buttons.grid(row=5, column=0, columnspan=2, sticky='w', pady=(16, 0))
        self.light_buttons = [
            ttk.Button(buttons, text=self.tr('common.read'), command=self.read_light),
            ttk.Button(buttons, text=self.tr('common.apply'), command=self.apply_light),
        ]
        for b in self.light_buttons:
            b.pack(side='left', padx=(0, 8))

        ttk.Separator(tab).grid(row=6, column=0, columnspan=2, sticky='we', pady=(16, 8))
        self.follow_dpi = tk.BooleanVar(value=bool(self.settings.get('dpi_follow', False)))
        ttk.Checkbutton(tab, text=self.tr('light.dpi_follow'), variable=self.follow_dpi,
                        command=self._toggle_follow).grid(row=7, column=0, columnspan=2, sticky='w')
        stage_row = ttk.Frame(tab)
        stage_row.grid(row=8, column=0, columnspan=2, sticky='w', pady=(6, 0))
        self.dpi_swatch = tk.Label(stage_row, width=4, relief='groove', background='#DDDDDD')
        self.dpi_swatch.pack(side='left')
        self.dpi_stage_text = tk.StringVar(value=self.tr('light.dpi_off'))
        ttk.Label(stage_row, textvariable=self.dpi_stage_text).pack(side='left', padx=8)
        ttk.Label(tab, text=self.tr('light.dpi_follow_hint'), wraplength=500, foreground='#666666',
                  justify='left').grid(row=9, column=0, columnspan=2, sticky='w', pady=(6, 0))

    def _build_indicator_tab(self, notebook):
        tab = ttk.Frame(notebook, padding=12)
        notebook.add(tab, text=self.tr('tab.indicator'))
        self.indicator_hint = tk.StringVar(value=self.tr('indicator.hint'))
        ttk.Label(tab, textvariable=self.indicator_hint).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
        self.indicator_names = [self.tr('indicator.option.%d' % i) for i in range(INDICATOR_OPTIONS)]
        self.indicator_values = [0, 0, 0]
        self.indicators = []
        for n in range(3):
            ttk.Label(tab, text=self.tr('indicator.slot', n=n + 1)).grid(row=n + 1, column=0, sticky='w', pady=4)
            box = ttk.Combobox(tab, values=self.indicator_names, state='readonly', width=28)
            box.current(0)
            box.grid(row=n + 1, column=1, sticky='w', padx=8, pady=4)
            self.indicators.append(box)
        buttons = ttk.Frame(tab)
        buttons.grid(row=5, column=0, columnspan=2, sticky='w', pady=(16, 0))
        self.indicator_buttons = [
            ttk.Button(buttons, text=self.tr('common.read'), command=self.read_indicator),
            ttk.Button(buttons, text=self.tr('common.apply'), command=self.apply_indicator),
        ]
        for b in self.indicator_buttons:
            b.pack(side='left', padx=(0, 8))

    def _build_diag_tab(self, notebook):
        tab = ttk.Frame(notebook, padding=12)
        notebook.add(tab, text=self.tr('tab.diagnostics'))
        buttons = ttk.Frame(tab)
        buttons.pack(fill='x')
        ttk.Button(buttons, text=self.tr('diag.refresh'), command=self.refresh_diagnostics).pack(side='left')
        ttk.Button(buttons, text=self.tr('diag.copy'), command=self._copy_diagnostics).pack(side='left', padx=8)
        self.diag_text = tk.Text(tab, height=14, wrap='none', font=('Consolas', 9))
        self.diag_text.pack(fill='both', expand=True, pady=(8, 0))

    # ---- helpers ------------------------------------------------------

    def _run(self, job, on_done):
        self.worker.submit(job, on_done)

    def _poll_results(self):
        try:
            while True:
                on_done, value, error = self.results.get_nowait()
                on_done(value, error)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_results)

    def _show_error(self, error):
        if isinstance(error, DeviceTimeout):
            self.status.set(self.tr('error.timeout'))
        elif isinstance(error, RuntimeError) and str(error) == 'not connected':
            self.status.set(self.tr('error.not_connected'))
        else:
            self.status.set(self.tr('error.generic', error=error))

    def _tick_clock(self):
        now = datetime.datetime.now()
        self.pc_time.set(self.tr('screen.pc_time', time=now.strftime('%d.%m.%Y  %H:%M:%S')))
        if (self.connected and self.has_screen and self.auto_sync.get()
                and time.monotonic() - self.last_sync >= AUTO_SYNC_SECONDS):
            self.sync_clock()
        self.root.after(1000, self._tick_clock)

    def _save_auto_sync(self):
        self.settings['auto_sync'] = bool(self.auto_sync.get())
        save_settings(self.settings)

    # ---- DPI colour mode ----------------------------------------------

    def _dpi_colors(self):
        """Stage colours: the manual's table, unless settings.json has a "dpi_colors" list of #RRGGBB."""
        custom = self.settings.get('dpi_colors')
        if (isinstance(custom, list) and custom
                and all(isinstance(c, str) and HEX_COLOR.fullmatch(c) for c in custom)):
            return tuple(c.upper() for c in custom)
        return protocol.DPI_STAGE_COLORS

    def _toggle_follow(self):
        self.settings['dpi_follow'] = bool(self.follow_dpi.get())
        save_settings(self.settings)
        if self.follow_dpi.get():
            if not self.connected:
                self.status.set(self.tr('light.dpi_wait_dock'))
            self._next_follow_try = 0.0  # the tick starts it as soon as the dock is connected
        else:
            self._stop_follow()

    def _start_follow(self):
        if self.following or not self.connected:
            return
        self.following = True
        self.dpi_stage_text.set(self.tr('light.dpi_waiting'))

        def done(_, error):
            if error is not None:
                self.following = False  # the tick retries
                self._show_error(error)
                return
            self.status.set(self.tr('light.dpi_started'))

        self._run(lambda worker: self.follower.start(), done)

    def _stop_follow(self):
        was_following = self.following
        self.following = False
        self.dpi_stage_text.set(self.tr('light.dpi_off'))
        self.dpi_swatch.configure(background='#DDDDDD')
        if not was_following:
            return

        def done(_, error):
            if error is not None:
                self._show_error(error)
                return
            self.status.set(self.tr('light.dpi_stopped'))
            self.read_light()

        self._run(lambda worker: self.follower.stop(), done)

    def _dpi_tick(self):
        self.root.after(DPI_POLL_MS, self._dpi_tick)
        if not self.connected:
            return
        if self.follow_dpi.get() and not self.following:
            if time.monotonic() >= self._next_follow_try:
                self._next_follow_try = time.monotonic() + 3
                self._start_follow()
            return
        if not self.following or self._poll_busy or not self.follower.running:
            return
        self._poll_busy = True
        self.follower.speed = self.speed.get()
        self.follower.brightness = self.brightness.get()

        def done(stage, error):
            self._poll_busy = False
            if error is not None:
                self._show_error(error)
                return
            self._show_stage(stage)

        self._run(lambda worker: self.follower.poll(), done)

    def _show_stage(self, stage):
        if stage is None:
            self.dpi_stage_text.set(self.tr('light.dpi_waiting'))
            return
        self.dpi_swatch.configure(background=self.follower.shown_color or stage_color(stage, self.follower.colors))
        dpi = self.follower.stage_dpi
        self.dpi_stage_text.set(self.tr('light.dpi_stage_dpi' if dpi else 'light.dpi_stage',
                                        stage=stage + 1, count=self.follower.stage_count, dpi=dpi))

    # ---- notification-area icon ---------------------------------------

    def _start_tray(self, start_hidden):
        from . import autostart
        from .tray import TrayIcon
        try:
            icon = TrayIcon(self.tr)
            started = icon.start()
        except Exception:
            logger.exception('tray icon is not available, the window will exit when closed')
            return
        if not started:
            return
        self.tray = icon
        self._autostart_enabled = autostart.is_enabled()
        self.root.bind('<Unmap>', self._on_unmap)
        if start_hidden:
            self.root.withdraw()
        self._tray_tick()

    def _on_unmap(self, event):
        if event.widget is self.root and self.root.state() == 'iconic':
            self.root.withdraw()  # minimising sends the window to the tray

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _tray_tick(self):
        if self.tray is None:
            return
        for event in self.tray.pop_events():
            if event == 'show':
                self.show_window()
            elif event == 'follow':
                self.follow_dpi.set(not self.follow_dpi.get())
                self._toggle_follow()
            elif event == 'autostart':
                self._toggle_autostart()
            elif event == 'exit':
                self.quit()
                return
        self._push_tray_state()
        self.root.after(TRAY_POLL_MS, self._tray_tick)

    def _push_tray_state(self):
        """Colour = what the dock shows now (grey when the mode is off); tooltip = the current level."""
        live = self.following and self.follower.stage is not None
        color = (self.follower.shown_color if live else None) or TRAY_INACTIVE_COLOR
        detail = self.dpi_stage_text.get() if live else self.status.get()
        state = (color, '%s\n%s' % (self.tr('tray.title'), detail), bool(self.follow_dpi.get()),
                 self._autostart_enabled)
        if state != self._tray_pushed:
            self._tray_pushed = state
            self.tray.set_state(*state)

    def _toggle_autostart(self):
        from . import autostart
        try:
            autostart.set_enabled(not self._autostart_enabled)
        except OSError as error:
            self.status.set(self.tr('tray.autostart_failed', error=error))
            return
        self._autostart_enabled = autostart.is_enabled()
        self.status.set(self.tr('tray.autostart_on' if self._autostart_enabled else 'tray.autostart_off'))

    def _on_close(self):
        """The window's close button: with a tray icon the program keeps running there, otherwise it exits."""
        if self.tray is not None:
            self.root.withdraw()
        else:
            self.quit()

    def quit(self):
        """Give the previous backlight back and tell the dongle the driver exited, then close for good."""
        if self.following and self.follower.running:
            self.following = False
            finished = threading.Event()

            def job(worker):
                try:
                    self.follower.stop()
                finally:
                    finished.set()

            self.worker.submit(job, None)
            finished.wait(CLOSE_WAIT_SECONDS)
        if self.tray is not None:
            self.tray.close()
            self.tray = None
        self.root.destroy()

    def _set_color(self, value):
        self.color = value.upper()
        self.swatch.configure(background=self.color)

    def _pick_color(self):
        _, value = colorchooser.askcolor(color=self.color, parent=self.root)
        if value:
            self._set_color(value)

    def _copy_diagnostics(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.diag_text.get('1.0', 'end').strip())
        self.status.set(self.tr('diag.copied'))

    # ---- device state -------------------------------------------------

    def _probe(self):
        self._run(probe, self._on_probe)
        self.root.after(PROBE_INTERVAL_MS, self._probe)

    def _on_probe(self, value, error):
        if error is not None:
            return
        changed, connection = value
        if not changed and self.probed:
            return
        self.probed = True
        self.connected = connection is not None
        self.has_screen = connection is not None and connection.channels.screen is not None
        if connection is None:
            self.status.set(self.tr('status.not_found'))
            return
        text = self.tr('status.connected', product=connection.product, pid='%04X' % connection.product_id)
        if connection.channels.screen is None:
            text += ' — ' + self.tr('status.no_screen')
        if connection.channels.command is None:
            text += ' — ' + self.tr('status.no_command')
        self.status.set(text)
        self.last_sync = 0.0
        if connection.channels.command is not None:
            if self.following:  # the dock was re-plugged: repeat the driver handshake
                self._run(lambda worker: self.follower.handshake(),
                          lambda _, error: self._show_error(error) if error is not None else None)
            self.read_light()
            self.read_indicator()
        self.refresh_diagnostics()

    def sync_clock(self):
        self.last_sync = time.monotonic()
        moment = datetime.datetime.now().replace(microsecond=0)

        def job(worker):
            return worker.require().sync_screen_clock(moment)

        def done(confirmed, error):
            if error is not None:
                self._show_error(error)
                return
            key = 'screen.synced_confirmed' if confirmed else 'screen.synced_sent'
            self.screen_result.set(self.tr(key, time=moment.strftime('%H:%M:%S')))

        self._run(job, done)

    def read_light(self):
        def done(light, error):
            if error is not None:
                self._show_error(error)
                return
            self.mode.current(min(light.mode, MODE_COUNT - 1))
            self._set_color('#%02X%02X%02X' % (light.red, light.green, light.blue))
            self.brightness.set(light.brightness)
            self.speed.set(light.speed)
            self.status.set(self.tr('common.read_ok'))

        self._run(lambda worker: worker.require().read_dock_light(), done)

    def apply_light(self):
        red, green, blue = device.parse_color(self.color)
        light = protocol.DockLight(mode=self.mode.current(), red=red, green=green, blue=blue,
                                   speed=self.speed.get(), brightness=self.brightness.get())

        def done(_, error):
            if error is not None:
                self._show_error(error)
                return
            self.status.set(self.tr('light.applied'))

        self._run(lambda worker: worker.require().set_dock_light(light), done)

    def _disable_indicators(self):
        for widget in self.indicators + self.indicator_buttons:
            widget.configure(state='disabled')
        self.indicator_hint.set(self.tr('indicator.unsupported'))

    def read_indicator(self):
        def done(slots, error):
            if isinstance(error, protocol.CommandRejected):
                self._disable_indicators()
                return
            if error is not None:
                self._show_error(error)
                return
            self.indicator_values = list(slots)
            for box, value in zip(self.indicators, slots):
                if value < INDICATOR_OPTIONS:
                    box.configure(values=self.indicator_names)
                    box.current(value)
                else:
                    box.configure(values=self.indicator_names + [self.tr('indicator.option.raw', value=value)])
                    box.current(INDICATOR_OPTIONS)
            self.status.set(self.tr('common.read_ok'))

        self._run(lambda worker: worker.require().read_indicator(), done)

    def apply_indicator(self):
        # A slot showing an unknown value read from the dock keeps that raw value.
        slots = tuple(box.current() if box.current() < INDICATOR_OPTIONS else raw
                      for box, raw in zip(self.indicators, self.indicator_values))

        def done(_, error):
            if isinstance(error, protocol.CommandRejected):
                self._disable_indicators()
                return
            if error is not None:
                self._show_error(error)
                return
            self.status.set(self.tr('indicator.applied'))

        self._run(lambda worker: worker.require().set_indicator(slots), done)

    def refresh_diagnostics(self):
        def job(worker):
            from . import hid_win
            interfaces = hid_win.enumerate_interfaces()
            channels = worker.connection.channels if worker.connection else None
            return device.diagnostics_report(interfaces, channels, self.tr, hid_win.known_report_ids())

        def done(text, error):
            if error is not None:
                self._show_error(error)
                return
            self.diag_text.delete('1.0', 'end')
            self.diag_text.insert('1.0', text)

        self._run(job, done)


def run(tr, start_hidden=False):
    from . import tray
    if not tray.acquire_single_instance():
        tray.signal_running_instance()  # the running copy shows its window
        return
    root = tk.Tk()
    App(root, tr, tray=True, start_hidden=start_hidden)
    root.mainloop()
