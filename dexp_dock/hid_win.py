"""Windows HID access through SetupAPI and hid.dll (ctypes, no third-party packages)."""
import ctypes
import logging
from ctypes import wintypes

from .channels import HidInterface, collection_number

logger = logging.getLogger(__name__)
MAX_DRAIN_REPORTS = 64
WRITE_TIMEOUT_MS = 1000

_setupapi = ctypes.WinDLL('setupapi', use_last_error=True)
_hid = ctypes.WinDLL('hid', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
HIDP_STATUS_SUCCESS = 0x00110000
HIDP_OUTPUT = 1
CAPS_ENTRY_SIZE = 72  # sizeof(HIDP_VALUE_CAPS) == sizeof(HIDP_BUTTON_CAPS)
CAPS_REPORT_ID_OFFSET = 2


class GUID(ctypes.Structure):
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('InterfaceClassGuid', GUID),
                ('Flags', wintypes.DWORD), ('Reserved', ctypes.c_void_p)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [('Size', wintypes.ULONG), ('VendorID', wintypes.USHORT),
                ('ProductID', wintypes.USHORT), ('VersionNumber', wintypes.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [('Usage', wintypes.USHORT), ('UsagePage', wintypes.USHORT),
                ('InputReportByteLength', wintypes.USHORT),
                ('OutputReportByteLength', wintypes.USHORT),
                ('FeatureReportByteLength', wintypes.USHORT),
                ('Reserved', wintypes.USHORT * 17),
                ('NumberLinkCollectionNodes', wintypes.USHORT),
                ('NumberInputButtonCaps', wintypes.USHORT),
                ('NumberInputValueCaps', wintypes.USHORT),
                ('NumberInputDataIndices', wintypes.USHORT),
                ('NumberOutputButtonCaps', wintypes.USHORT),
                ('NumberOutputValueCaps', wintypes.USHORT),
                ('NumberOutputDataIndices', wintypes.USHORT),
                ('NumberFeatureButtonCaps', wintypes.USHORT),
                ('NumberFeatureValueCaps', wintypes.USHORT),
                ('NumberFeatureDataIndices', wintypes.USHORT)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                ('hEvent', wintypes.HANDLE)]


_hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
_hid.HidD_GetHidGuid.restype = None
_hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
_hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
_hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
_hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
_hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
_hid.HidD_FreePreparsedData.restype = wintypes.BOOLEAN
_hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_GetProductString.restype = wintypes.BOOLEAN
_hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
_hid.HidP_GetCaps.restype = ctypes.c_long
for _name in ('HidP_GetValueCaps', 'HidP_GetButtonCaps'):
    _fn = getattr(_hid, _name)
    _fn.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
    _fn.restype = ctypes.c_long

_setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
_setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID),
                                                   wintypes.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
_setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                        ctypes.c_void_p, wintypes.DWORD,
                                                        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
_setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

_kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
_kernel32.ResetEvent.restype = wintypes.BOOL
_kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
_kernel32.ReadFile.restype = wintypes.BOOL
_kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
_kernel32.WriteFile.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
                                          ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
_kernel32.GetOverlappedResult.restype = wintypes.BOOL
_kernel32.CancelIo.argtypes = [wintypes.HANDLE]
_kernel32.CancelIo.restype = wintypes.BOOL


class HidError(OSError):
    pass


def _last_error(what):
    code = ctypes.get_last_error()
    return HidError(code, '%s failed: %s' % (what, ctypes.FormatError(code).strip()))


def _open(path, access, flags=0):
    handle = _kernel32.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                   None, OPEN_EXISTING, flags, None)
    if handle is None or handle == INVALID_HANDLE_VALUE:
        raise _last_error('CreateFile')
    return handle


def _interface_paths():
    guid = GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = _setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                          DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if info is None or info == INVALID_HANDLE_VALUE:
        raise _last_error('SetupDiGetClassDevs')
    paths = []
    try:
        index = 0
        while True:
            data = SP_DEVICE_INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not _setupapi.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(guid), index,
                                                         ctypes.byref(data)):
                break
            index += 1
            required = wintypes.DWORD()
            _setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(data), None, 0,
                                                      ctypes.byref(required), None)
            buf = ctypes.create_string_buffer(required.value)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W: DWORD cbSize + WCHAR[]; cbSize is 8 on x64, 6 on x86.
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not _setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(data), buf, required,
                                                              None, None):
                continue
            paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(info)
    return paths


def _output_report_ids(preparsed, caps):
    ids = set()
    for fn, count in ((_hid.HidP_GetValueCaps, caps.NumberOutputValueCaps),
                      (_hid.HidP_GetButtonCaps, caps.NumberOutputButtonCaps)):
        if not count:
            continue
        buf = ctypes.create_string_buffer(CAPS_ENTRY_SIZE * count)
        length = wintypes.USHORT(count)
        if fn(HIDP_OUTPUT, buf, ctypes.byref(length), preparsed) == HIDP_STATUS_SUCCESS:
            ids.update(buf.raw[i * CAPS_ENTRY_SIZE + CAPS_REPORT_ID_OFFSET] for i in range(length.value))
    return ids


def _describe(path):
    """Return (HidInterface, output report id or None) for one collection path."""
    # Access 0 queries attributes even for collections Windows keeps exclusive (mouse, keyboard).
    handle = _open(path, 0)
    try:
        attrs = HIDD_ATTRIBUTES()
        attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
        if not _hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
            raise _last_error('HidD_GetAttributes')
        caps = HIDP_CAPS()
        report_ids = set()
        preparsed = ctypes.c_void_p()
        if _hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            try:
                _hid.HidP_GetCaps(preparsed, ctypes.byref(caps))
                report_ids = _output_report_ids(preparsed, caps)
            finally:
                _hid.HidD_FreePreparsedData(preparsed)
        name = ctypes.create_unicode_buffer(128)
        product = name.value if _hid.HidD_GetProductString(handle, name, ctypes.sizeof(name)) else ''
    finally:
        _kernel32.CloseHandle(handle)
    iface = HidInterface(path=path, vendor_id=attrs.VendorID, product_id=attrs.ProductID,
                         usage_page=caps.UsagePage, usage=caps.Usage,
                         input_length=caps.InputReportByteLength,
                         output_length=caps.OutputReportByteLength,
                         feature_length=caps.FeatureReportByteLength, product=product)
    return iface, (min(report_ids) if len(report_ids) == 1 else None)


_report_ids = {}


def enumerate_interfaces():
    result = []
    for path in _interface_paths():
        try:
            iface, report_id = _describe(path)
        except HidError:
            continue
        _report_ids[path] = report_id
        result.append(iface)
    return result


def output_report_id(iface):
    return _report_ids.get(iface.path)


def known_report_ids():
    return dict(_report_ids)


class HidPort:
    """Overlapped read/write port on one HID collection; a read is always armed."""

    def __init__(self, iface):
        self.iface = iface
        self.output_length = iface.output_length
        self.report_id = output_report_id(iface)
        self._tag = 'col%s' % (collection_number(iface.path) or '?')
        logger.info('%s open: %s in=%d out=%d report_id=%s', self._tag, iface.path, iface.input_length,
                    iface.output_length, self.report_id)
        self._handle = _open(iface.path, GENERIC_READ | GENERIC_WRITE, FILE_FLAG_OVERLAPPED)
        self._read_event = _kernel32.CreateEventW(None, True, False, None)
        self._write_event = _kernel32.CreateEventW(None, True, False, None)
        self._read_buf = ctypes.create_string_buffer(max(iface.input_length, 1))
        self._read_ov = OVERLAPPED()
        self._pending = False
        self._arm()

    def _arm(self):
        if self.iface.input_length == 0:
            return
        _kernel32.ResetEvent(self._read_event)
        self._read_ov = OVERLAPPED()
        self._read_ov.hEvent = self._read_event
        ok = _kernel32.ReadFile(self._handle, self._read_buf, self.iface.input_length, None,
                                ctypes.byref(self._read_ov))
        if not ok and ctypes.get_last_error() != ERROR_IO_PENDING:
            raise _last_error('ReadFile')
        self._pending = True

    def read(self, timeout_ms):
        if not self._pending:
            return None
        if _kernel32.WaitForSingleObject(self._read_event, int(timeout_ms)) != WAIT_OBJECT_0:
            if timeout_ms:
                logger.debug('%s read: nothing in %d ms', self._tag, timeout_ms)
            return None
        count = wintypes.DWORD()
        if not _kernel32.GetOverlappedResult(self._handle, ctypes.byref(self._read_ov), ctypes.byref(count), False):
            self._pending = False
            raise _last_error('ReadFile')
        data = self._read_buf.raw[:count.value]
        logger.debug('%s read: %s', self._tag, data.hex(' '))
        self._arm()
        return data

    def drain(self):
        """Throw away reports that are already queued and return them (callers may still want the events)."""
        # Bounded: a dongle that streams status reports would otherwise keep this loop busy forever.
        dropped = []
        for _ in range(MAX_DRAIN_REPORTS):
            report = self.read(0)
            if report is None:
                return dropped
            dropped.append(report)
        logger.warning('%s drain: input keeps coming, stopped after %d reports', self._tag, MAX_DRAIN_REPORTS)
        return dropped

    def write(self, data):
        if len(data) != self.output_length:
            raise ValueError('output report must be %d bytes, got %d' % (self.output_length, len(data)))
        logger.debug('%s write: %s', self._tag, bytes(data).hex(' '))
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        ov = OVERLAPPED()
        _kernel32.ResetEvent(self._write_event)
        ov.hEvent = self._write_event
        ok = _kernel32.WriteFile(self._handle, buf, len(data), None, ctypes.byref(ov))
        if not ok and ctypes.get_last_error() != ERROR_IO_PENDING:
            raise _last_error('WriteFile')
        if _kernel32.WaitForSingleObject(self._write_event, WRITE_TIMEOUT_MS) != WAIT_OBJECT_0:
            logger.warning('%s write: not completed in %d ms, cancelling', self._tag, WRITE_TIMEOUT_MS)
            _kernel32.CancelIo(self._handle)
            count = wintypes.DWORD()
            _kernel32.GetOverlappedResult(self._handle, ctypes.byref(ov), ctypes.byref(count), True)
            self._pending = False
            self._arm()
            raise HidError(0, 'WriteFile timed out')
        count = wintypes.DWORD()
        if not _kernel32.GetOverlappedResult(self._handle, ctypes.byref(ov), ctypes.byref(count), False):
            raise _last_error('WriteFile')
        logger.debug('%s write: done, %d bytes', self._tag, count.value)

    def close(self):
        if self._handle:
            logger.info('%s close', self._tag)
            _kernel32.CancelIo(self._handle)
            if self._pending:
                count = wintypes.DWORD()
                _kernel32.GetOverlappedResult(self._handle, ctypes.byref(self._read_ov), ctypes.byref(count), True)
            _kernel32.CloseHandle(self._handle)
            _kernel32.CloseHandle(self._read_event)
            _kernel32.CloseHandle(self._write_event)
            self._handle = None
            self._pending = False
