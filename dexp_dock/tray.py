"""Notification-area icon (Windows, ctypes only).

The icon lives on its own thread together with a hidden window and its message loop. It never touches Tk:
clicks and menu choices are put on a queue (`pop_events`) that the GUI polls, and the GUI pushes the icon's
colour, tooltip and menu check marks with `set_state`.
"""
import ctypes
import logging
import queue
import sys
import threading
from ctypes import wintypes

logger = logging.getLogger(__name__)

ICON_SIZE = 32
RIM_COLOR = (40, 40, 40)

WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_TRAY = WM_APP + 1    # callback of the shell for our icon
WM_STATE = WM_APP + 2   # the GUI changed the state (posted by set_state)
WM_SHOW = WM_APP + 3    # a second instance asks us to show the window

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
MF_STRING, MF_CHECKED, MF_SEPARATOR = 0x0, 0x8, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IDI_APPLICATION = 32512
ERROR_ALREADY_EXISTS = 183
TOOLTIP_LENGTH = 127

CLASS_NAME = 'DexpDockTrayWindow'
MUTEX_NAME = 'Local\\DexpDockSingleInstance'

CMD_OPEN, CMD_FOLLOW, CMD_AUTOSTART, CMD_EXIT = 1, 2, 3, 4


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def icon_pixels(rgb, size=ICON_SIZE):
    """Premultiplied BGRA pixels: a filled circle with a dark rim on a transparent background."""
    red, green, blue = rgb
    centre = (size - 1) / 2
    radius = size / 2 - 1.5
    out = bytearray()
    for y in range(size):
        for x in range(size):
            distance = ((x - centre) ** 2 + (y - centre) ** 2) ** 0.5
            alpha = _clamp(radius + 0.5 - distance)
            fill = _clamp(radius - 2.5 - distance + 0.5)  # 1 inside, 0 on the rim
            r = RIM_COLOR[0] + (red - RIM_COLOR[0]) * fill
            g = RIM_COLOR[1] + (green - RIM_COLOR[1]) * fill
            b = RIM_COLOR[2] + (blue - RIM_COLOR[2]) * fill
            out += bytes((int(b * alpha), int(g * alpha), int(r * alpha), int(alpha * 255)))
    return bytes(out)


def parse_hex_color(text, default=(128, 128, 128)):
    text = (text or '').lstrip('#')
    if len(text) != 6:
        return default
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


if sys.platform == 'win32':
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    HANDLE = ctypes.c_void_p
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HANDLE, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', WNDPROC), ('cbClsExtra', ctypes.c_int),
                    ('cbWndExtra', ctypes.c_int), ('hInstance', HANDLE), ('hIcon', HANDLE),
                    ('hCursor', HANDLE), ('hbrBackground', HANDLE), ('lpszMenuName', wintypes.LPCWSTR),
                    ('lpszClassName', wintypes.LPCWSTR)]

    class GUID(ctypes.Structure):
        _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD),
                    ('Data4', ctypes.c_ubyte * 8)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('hWnd', HANDLE), ('uID', wintypes.UINT),
                    ('uFlags', wintypes.UINT), ('uCallbackMessage', wintypes.UINT), ('hIcon', HANDLE),
                    ('szTip', wintypes.WCHAR * 128), ('dwState', wintypes.DWORD),
                    ('dwStateMask', wintypes.DWORD), ('szInfo', wintypes.WCHAR * 256),
                    ('uVersion', wintypes.UINT), ('szInfoTitle', wintypes.WCHAR * 64),
                    ('dwInfoFlags', wintypes.DWORD), ('guidItem', GUID), ('hBalloonIcon', HANDLE)]

    class ICONINFO(ctypes.Structure):
        _fields_ = [('fIcon', wintypes.BOOL), ('xHotspot', wintypes.DWORD), ('yHotspot', wintypes.DWORD),
                    ('hbmMask', HANDLE), ('hbmColor', HANDLE)]

    def _prototype(function, restype, *argtypes):
        function.restype = restype
        function.argtypes = list(argtypes)

    _prototype(user32.DefWindowProcW, LRESULT, HANDLE, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    _prototype(user32.RegisterClassW, wintypes.ATOM, ctypes.POINTER(WNDCLASSW))
    _prototype(user32.UnregisterClassW, wintypes.BOOL, wintypes.LPCWSTR, HANDLE)
    _prototype(user32.CreateWindowExW, HANDLE, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
               wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, HANDLE, HANDLE,
               HANDLE, ctypes.c_void_p)
    _prototype(user32.DestroyWindow, wintypes.BOOL, HANDLE)
    _prototype(user32.GetMessageW, ctypes.c_int, ctypes.POINTER(wintypes.MSG), HANDLE, wintypes.UINT,
               wintypes.UINT)
    _prototype(user32.TranslateMessage, wintypes.BOOL, ctypes.POINTER(wintypes.MSG))
    _prototype(user32.DispatchMessageW, LRESULT, ctypes.POINTER(wintypes.MSG))
    _prototype(user32.PostMessageW, wintypes.BOOL, HANDLE, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    _prototype(user32.PostQuitMessage, None, ctypes.c_int)
    _prototype(user32.RegisterWindowMessageW, wintypes.UINT, wintypes.LPCWSTR)
    _prototype(user32.FindWindowW, HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR)
    _prototype(user32.CreatePopupMenu, HANDLE)
    _prototype(user32.AppendMenuW, wintypes.BOOL, HANDLE, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR)
    _prototype(user32.SetMenuDefaultItem, wintypes.BOOL, HANDLE, wintypes.UINT, wintypes.UINT)
    _prototype(user32.TrackPopupMenu, wintypes.BOOL, HANDLE, wintypes.UINT, ctypes.c_int, ctypes.c_int,
               ctypes.c_int, HANDLE, ctypes.c_void_p)
    _prototype(user32.DestroyMenu, wintypes.BOOL, HANDLE)
    _prototype(user32.SetForegroundWindow, wintypes.BOOL, HANDLE)
    _prototype(user32.GetCursorPos, wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
    _prototype(user32.CreateIconIndirect, HANDLE, ctypes.POINTER(ICONINFO))
    _prototype(user32.DestroyIcon, wintypes.BOOL, HANDLE)
    _prototype(user32.LoadIconW, HANDLE, HANDLE, ctypes.c_void_p)
    _prototype(shell32.Shell_NotifyIconW, wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW))
    _prototype(gdi32.CreateBitmap, HANDLE, ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT,
               ctypes.c_void_p)
    _prototype(gdi32.DeleteObject, wintypes.BOOL, HANDLE)
    _prototype(kernel32.GetModuleHandleW, HANDLE, wintypes.LPCWSTR)
    _prototype(kernel32.CreateMutexW, HANDLE, ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)


_mutex_handle = None


def acquire_single_instance():
    """True for the first instance; False if another one already runs (it keeps the named mutex)."""
    global _mutex_handle
    if sys.platform != 'win32':
        return True
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return False
    _mutex_handle = handle  # keep it alive for the lifetime of the process
    return True


def signal_running_instance():
    """Ask the already running instance to show its window."""
    if sys.platform != 'win32':
        return
    hwnd = user32.FindWindowW(CLASS_NAME, None)
    if hwnd:
        user32.PostMessageW(hwnd, WM_SHOW, 0, 0)


class TrayIcon:
    """`tr` is the translator. Events for the GUI: 'show', 'follow', 'autostart', 'exit'."""

    def __init__(self, tr):
        self.tr = tr
        self.events = queue.Queue()
        self._lock = threading.Lock()
        self._state = {'color': '#808080', 'tooltip': '', 'follow': False, 'autostart': False}
        self._ready = threading.Event()
        self._hwnd = None
        self._thread = None
        self._icons = {}
        self._wndproc = None
        self._current_icon = None
        self._taskbar_created = 0
        self._added = False

    # ---- called from the GUI thread ------------------------------------

    def start(self, timeout=3.0):
        if sys.platform != 'win32':
            return False
        self._thread = threading.Thread(target=self._run, name='tray', daemon=True)
        self._thread.start()
        return self._ready.wait(timeout) and self._hwnd is not None

    def set_state(self, color, tooltip, follow, autostart):
        with self._lock:
            self._state = {'color': color, 'tooltip': tooltip, 'follow': bool(follow),
                           'autostart': bool(autostart)}
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_STATE, 0, 0)

    def pop_events(self):
        out = []
        try:
            while True:
                out.append(self.events.get_nowait())
        except queue.Empty:
            return out

    def close(self):
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(2.0)

    # ---- tray thread -----------------------------------------------------

    def _run(self):
        instance = kernel32.GetModuleHandleW(None)
        try:
            self._wndproc = WNDPROC(self._window_proc)
            window_class = WNDCLASSW()
            window_class.lpfnWndProc = self._wndproc
            window_class.hInstance = instance
            window_class.lpszClassName = CLASS_NAME
            user32.RegisterClassW(ctypes.byref(window_class))
            self._hwnd = user32.CreateWindowExW(0, CLASS_NAME, 'Dexp Dock', 0, 0, 0, 0, 0, None, None,
                                                instance, None)
            if not self._hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            self._taskbar_created = user32.RegisterWindowMessageW('TaskbarCreated')
            self._add_icon()
        except Exception:
            logger.exception('tray icon could not start')
            self._hwnd = None
            self._ready.set()
            return
        self._ready.set()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        for icon in self._icons.values():
            user32.DestroyIcon(icon)
        # The class keeps our callback: drop it so a later TrayIcon in this process gets its own.
        user32.UnregisterClassW(CLASS_NAME, instance)

    def _window_proc(self, hwnd, message, wparam, lparam):
        try:
            if message == WM_TRAY:
                event = lparam & 0xFFFF
                if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self.events.put('show')
                elif event == WM_RBUTTONUP:
                    self._show_menu(hwnd)
                return 0
            if message == WM_STATE:
                self._modify_icon()
                return 0
            if message == WM_SHOW:
                self.events.put('show')
                return 0
            if self._taskbar_created and message == self._taskbar_created:
                self._added = False
                self._add_icon()  # Explorer restarted: put the icon back
                return 0
            if message == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                self._remove_icon()
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            logger.exception('tray window procedure failed')
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _icon_for(self, color):
        rgb = parse_hex_color(color)
        if rgb not in self._icons:
            self._icons[rgb] = self._make_icon(rgb)
        return self._icons[rgb]

    @staticmethod
    def _make_icon(rgb):
        pixels = ctypes.create_string_buffer(icon_pixels(rgb), ICON_SIZE * ICON_SIZE * 4)
        mask = ctypes.create_string_buffer(ICON_SIZE * ICON_SIZE // 8)
        color_bitmap = gdi32.CreateBitmap(ICON_SIZE, ICON_SIZE, 1, 32, pixels)
        mask_bitmap = gdi32.CreateBitmap(ICON_SIZE, ICON_SIZE, 1, 1, mask)
        info = ICONINFO(True, 0, 0, mask_bitmap, color_bitmap)
        icon = user32.CreateIconIndirect(ctypes.byref(info))
        gdi32.DeleteObject(color_bitmap)
        gdi32.DeleteObject(mask_bitmap)
        return icon or user32.LoadIconW(None, IDI_APPLICATION)

    def _notify_data(self):
        with self._lock:
            state = dict(self._state)
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAY
        data.hIcon = self._icon_for(state['color'])
        data.szTip = state['tooltip'][:TOOLTIP_LENGTH]
        return data

    def _add_icon(self):
        if not self._added:
            self._added = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._notify_data())))

    def _modify_icon(self):
        if not self._added:
            self._add_icon()
        else:
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._notify_data()))

    def _remove_icon(self):
        if self._added:
            data = NOTIFYICONDATAW()
            data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            data.hWnd = self._hwnd
            data.uID = 1
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
            self._added = False

    def _show_menu(self, hwnd):
        with self._lock:
            follow, autostart = self._state['follow'], self._state['autostart']
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, CMD_OPEN, self.tr('tray.open'))
        user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if follow else 0), CMD_FOLLOW, self.tr('tray.follow'))
        user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if autostart else 0), CMD_AUTOSTART,
                           self.tr('tray.autostart'))
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, CMD_EXIT, self.tr('tray.exit'))
        user32.SetMenuDefaultItem(menu, CMD_OPEN, 0)
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(hwnd)  # otherwise the menu does not close when the user clicks elsewhere
        choice = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON, point.x, point.y,
                                       0, hwnd, None)
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        events = {CMD_OPEN: 'show', CMD_FOLLOW: 'follow', CMD_AUTOSTART: 'autostart', CMD_EXIT: 'exit'}
        if choice in events:
            self.events.put(events[choice])
