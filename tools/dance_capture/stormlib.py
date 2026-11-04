"""Read and create the MPQ archives used by the Windows Spotlight PoC."""

import ctypes
from ctypes import wintypes
from pathlib import Path


DLL_PATH = Path(__file__).with_name("vendor") / "StormLib.dll"
if not DLL_PATH.is_file():
    raise FileNotFoundError(f"Install the Windows x64 StormLib DLL at {DLL_PATH}.")

_dll = ctypes.WinDLL(str(DLL_PATH), use_last_error=True)
_handle_pointer = ctypes.POINTER(wintypes.HANDLE)
_dword_pointer = ctypes.POINTER(wintypes.DWORD)

STREAM_FLAG_READ_ONLY = 0x00000100
MPQ_CREATE_LISTFILE_AND_ATTRIBUTES = 0x00300000
MPQ_FILE_COMPRESS = 0x00000200
MPQ_COMPRESSION_ZLIB = 0x02


def _bind(name, result, *arguments):
    function = getattr(_dll, name)
    function.restype = result
    function.argtypes = arguments
    return function


_open_archive = _bind("SFileOpenArchive", ctypes.c_bool, wintypes.LPCWSTR, wintypes.DWORD,
                      wintypes.DWORD, _handle_pointer)
_create_archive = _bind("SFileCreateArchive", ctypes.c_bool, wintypes.LPCWSTR, wintypes.DWORD,
                        wintypes.DWORD, _handle_pointer)
_close_archive = _bind("SFileCloseArchive", ctypes.c_bool, wintypes.HANDLE)
_open_file = _bind("SFileOpenFileEx", ctypes.c_bool, wintypes.HANDLE, ctypes.c_char_p,
                   wintypes.DWORD, _handle_pointer)
_file_size = _bind("SFileGetFileSize", wintypes.DWORD, wintypes.HANDLE, _dword_pointer)
_read_file = _bind("SFileReadFile", ctypes.c_bool, wintypes.HANDLE, ctypes.c_void_p,
                   wintypes.DWORD, _dword_pointer, ctypes.c_void_p)
_close_file = _bind("SFileCloseFile", ctypes.c_bool, wintypes.HANDLE)
_set_locale = _bind("SFileSetLocale", wintypes.DWORD, wintypes.DWORD)
_create_file = _bind("SFileCreateFile", ctypes.c_bool, wintypes.HANDLE, ctypes.c_char_p,
                     ctypes.c_uint64, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, _handle_pointer)
_write_file = _bind("SFileWriteFile", ctypes.c_bool, wintypes.HANDLE, ctypes.c_void_p,
                    wintypes.DWORD, wintypes.DWORD)
_finish_file = _bind("SFileFinishFile", ctypes.c_bool, wintypes.HANDLE)


def _check(ok, operation):
    if not ok:
        code = ctypes.get_last_error()
        raise OSError(code, f"{operation}: {ctypes.FormatError(code)}")


class Archive:
    def __init__(self, path, create=False, capacity=16384):
        self.path = Path(path)
        self.handle = wintypes.HANDLE()
        self.writable = create
        if create:
            if self.path.exists():
                raise FileExistsError(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # With no version flag StormLib creates an MPQ v1 for WoW 3.3.5a.
            _check(_create_archive(str(self.path), MPQ_CREATE_LISTFILE_AND_ATTRIBUTES, capacity,
                                   ctypes.byref(self.handle)), f"create {self.path}")
        else:
            _check(_open_archive(str(self.path), 0, STREAM_FLAG_READ_ONLY,
                                 ctypes.byref(self.handle)), f"open {self.path}")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.handle:
            _check(_close_archive(self.handle), f"close {self.path}")
            self.handle = wintypes.HANDLE()

    def read(self, name):
        handle = wintypes.HANDLE()
        previous = _set_locale(0)
        try:
            _check(_open_file(self.handle, name.encode("utf-8"), 0, ctypes.byref(handle)), f"open {name}")
            high = wintypes.DWORD()
            size = _file_size(handle, ctypes.byref(high))
            if high.value or size == 0xFFFFFFFF:
                raise ValueError(f"Unsupported MPQ member size: {name}")
            buffer = ctypes.create_string_buffer(size)
            count = wintypes.DWORD()
            _check(_read_file(handle, buffer, size, ctypes.byref(count), None), f"read {name}")
            if count.value != size:
                raise OSError(f"Short MPQ read: {name} ({count.value} of {size} bytes)")
            return buffer.raw
        finally:
            if handle:
                _close_file(handle)
            _set_locale(previous)

    def write(self, name, data):
        if not self.writable:
            raise PermissionError("Input archives are read-only.")
        handle = wintypes.HANDLE()
        _check(_create_file(self.handle, name.encode("utf-8"), 0, len(data), 0, MPQ_FILE_COMPRESS,
                            ctypes.byref(handle)), f"create {name}")
        try:
            if data:
                buffer = ctypes.create_string_buffer(data)
                _check(_write_file(handle, buffer, len(data), MPQ_COMPRESSION_ZLIB), f"write {name}")
        finally:
            _check(_finish_file(handle), f"finish {name}")
