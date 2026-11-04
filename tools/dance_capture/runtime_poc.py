"""Apply a captured dance to a running isolated Windows lab client."""

import argparse
import ctypes
from ctypes import wintypes
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import math
import os
from pathlib import Path
import struct

if __package__:
    from . import client_poc
else:
    import client_poc


CLIENT_HASH = "28287cd94e6ab2d6e68865f49314b456d2750dcb5d0b8ecca12eeddf72b7bf80"
DEFAULT_CLIENT = Path(r"C:\WoWModding\SpotlightPoC\LiveActor")
PROCESS_RIGHTS = 0x0400 | 0x0020 | 0x0010 | 0x0008  # query, VM write/read/operation
MEM_COMMIT = 0x1000
MEM_PRIVATE = 0x20000
PAGE_READWRITE = 0x04
CHUNK_SIZE = 2 * 1024 * 1024
ANCHOR_BYTES = 1024


class TrackNotReadyError(ValueError):
    """The model's animation is not currently available for an unambiguous update."""


class PoseClipError(ValueError):
    """The selected pose file cannot be converted to the animation track."""


class MemoryRegion(ctypes.Structure):
    _fields_ = [
        ("base", ctypes.c_void_p),
        ("allocation_base", ctypes.c_void_p),
        ("allocation_protect", wintypes.DWORD),
        ("partition", wintypes.WORD),
        ("size", ctypes.c_size_t),
        ("state", wintypes.DWORD),
        ("protect", wintypes.DWORD),
        ("type", wintypes.DWORD),
    ]


class ClientProcess:
    def __init__(self, pid, executable):
        if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise ValueError("Use 64-bit Python on Windows for the isolated 32-bit client.")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.open = kernel.OpenProcess
        self.open.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.open.restype = wintypes.HANDLE
        self.close = kernel.CloseHandle
        self.close.argtypes = (wintypes.HANDLE,)
        self.close.restype = wintypes.BOOL
        self.query_path = kernel.QueryFullProcessImageNameW
        self.query_path.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        self.query_path.restype = wintypes.BOOL
        self.query_region = kernel.VirtualQueryEx
        self.query_region.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MemoryRegion), ctypes.c_size_t)
        self.query_region.restype = ctypes.c_size_t
        memory_arguments = (
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
        )
        self.read_memory = kernel.ReadProcessMemory
        self.read_memory.argtypes = memory_arguments
        self.read_memory.restype = wintypes.BOOL
        self.write_memory = kernel.WriteProcessMemory
        self.write_memory.argtypes = memory_arguments
        self.write_memory.restype = wintypes.BOOL

        self.handle = self.open(PROCESS_RIGHTS, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            name = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(name))
            if not self.query_path(self.handle, 0, name, ctypes.byref(length)):
                raise ctypes.WinError(ctypes.get_last_error())
            if Path(name.value).resolve() != executable:
                raise ValueError("The PID does not belong to the selected isolated lab client.")
        except (OSError, ValueError):
            self.close(self.handle)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close(self.handle)

    def read(self, address, size):
        buffer = ctypes.create_string_buffer(size)
        transferred = ctypes.c_size_t()
        if self.read_memory(self.handle, address, buffer, size, ctypes.byref(transferred)) and transferred.value == size:
            return buffer.raw
        return None

    def write(self, address, data):
        transferred = ctypes.c_size_t()
        if not self.write_memory(self.handle, address, data, len(data), ctypes.byref(transferred)):
            raise ctypes.WinError(ctypes.get_last_error())
        if transferred.value != len(data):
            raise OSError("The client accepted only part of the replacement track.")

    def private_chunks(self, overlap):
        region = MemoryRegion()
        cursor = 0
        while cursor < 2**32 and self.query_region(self.handle, cursor, ctypes.byref(region), ctypes.sizeof(region)):
            base = region.base or 0
            cursor = base + region.size
            if (region.state, region.type, region.protect) != (MEM_COMMIT, MEM_PRIVATE, PAGE_READWRITE):
                continue
            for address in range(base, cursor, CHUNK_SIZE):
                data = self.read(address, min(cursor - address, CHUNK_SIZE + overlap))
                if data is not None:
                    yield address, data


def has_unit_rotations(data):
    for components in client_poc.QUATERNION.iter_unpack(data):
        rotation = [(value + 32768 if value < 0 else value - 32767) / 32767 for value in components]
        if not math.isclose(math.hypot(*rotation), 1, abs_tol=0.002):
            return False
    return True


def replace_animation(process, source, replacement, tracks, translations):
    spans = sorted([span for track in tracks.values() for span in track.ranges()] + translations)
    immutable = []
    cursor = 0
    for start, end in spans:
        if start < cursor or end > len(source):
            raise ValueError("Unexpected overlapping animation data.")
        immutable.append((cursor, start))
        cursor = end
    immutable.append((cursor, len(source)))
    anchor = source[:ANCHOR_BYTES]
    if immutable[0][1] < len(anchor):
        raise ValueError("Expected immutable data at the start of the animation.")

    def matches_source(window):
        return (window is not None and len(window) == len(source)
                and all(window[start:end] == source[start:end] for start, end in immutable))

    def valid_tracks(window):
        for track in tracks.values():
            (start_time, end_time), (start_key, end_key) = track.ranges()
            times = struct.unpack(f"<{len(track.timestamps)}I", window[start_time:end_time])
            if (times[0] != 0 or times[-1] != track.timestamps[-1]
                    or any(a >= b for a, b in zip(times, times[1:]))
                    or not has_unit_rotations(window[start_key:end_key])):
                return False
        return all(window[start:end] in (source[start:end], bytes(end - start)) for start, end in translations)

    matches = set()
    for base, data in process.private_chunks(len(source) - 1):
        index = data.find(anchor)
        while index >= 0:
            candidate = data[index:index + len(source)]
            if matches_source(candidate) and valid_tracks(candidate):
                matches.add(base + index)
            index = data.find(anchor, index + 1)

    if len(matches) != 1:
        raise TrackNotReadyError(f"Expected one resident Human Male animation track, found {len(matches)}. Open the preview first.")
    address = matches.pop()
    window = process.read(address, len(source))
    if not matches_source(window) or not valid_tracks(window):
        raise TrackNotReadyError("The preview animation changed during the scan. Keep the model open and try again.")

    changed = [(start, end) for start, end in spans if window[start:end] != replacement[start:end]]
    if changed:
        first = changed[0][0]
        last = changed[-1][1]
        # The bytes outside the declared ranges were matched against the stock asset above.
        # Use one write so the live model cannot observe a series of separately applied tracks.
        payload = replacement[first:last]
        try:
            process.write(address + first, payload)
            if process.read(address, len(source)) != replacement:
                raise OSError("The running client did not retain the replacement animation.")
        except OSError:
            if matches_source(process.read(address, len(source))):
                process.write(address + first, window[first:last])
            raise
    return {"address": hex(address), "changed_bytes": sum(a != b for a, b in zip(window, replacement)),
            "animation_sha256": sha256(replacement).hexdigest()}


def apply(pid, client_dir, pose_path, stormlib_module):
    client_dir = client_dir.resolve()
    if client_dir == client_poc.DEFAULT_DATA.resolve().parent:
        raise ValueError("Select the isolated Spotlight client copy.")
    executable = client_dir / "WoW.exe"
    if sha256(executable.read_bytes()).hexdigest() != CLIENT_HASH:
        raise ValueError("The executable does not match the verified 3.3.5a lab build.")
    spec = spec_from_file_location("dance_runtime_stormlib", stormlib_module)
    if spec is None or spec.loader is None:
        raise ImportError("Pass the path to the StormLib Python wrapper.")
    stormlib = module_from_spec(spec)
    spec.loader.exec_module(stormlib)
    data_path = client_dir / "Data"
    model = client_poc.read_source(stormlib.Archive, data_path / "patch-3.MPQ", client_poc.MODEL_PATH, client_poc.MODEL_HASH)
    source = client_poc.read_source(stormlib.Archive, data_path / "patch-2.MPQ", client_poc.ANIMATION_PATH, client_poc.ANIMATION_HASH)
    tracks = client_poc.full_body_tracks(model, source)
    translations = client_poc.translation_ranges(model)
    if pose_path is None:
        target = source
        stats = {"rotation_tracks": len(tracks)}
    else:
        try:
            with pose_path.open(encoding="utf-8") as stream:
                clip = json.load(stream)
            target, stats = client_poc.bake_clip(model, source, clip)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
            raise PoseClipError(str(error)) from error
    with ClientProcess(pid, executable) as process:
        result = replace_animation(process, source, target, tracks, translations)
    return {"pid": pid, "animation": client_poc.ANIMATION_ID, **stats, **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int, help="PID of the running isolated WoW client")
    parser.add_argument("pose", type=Path, nargs="?", help="Spotlight motion or MediaPipe pose JSON")
    parser.add_argument("--restore", action="store_true", help="Restore the stock animation")
    parser.add_argument("--client-dir", type=Path, default=DEFAULT_CLIENT)
    parser.add_argument("--stormlib-module", type=Path, default=client_poc.DEFAULT_STORMLIB)
    args = parser.parse_args()
    if args.restore == (args.pose is not None):
        parser.error("Pass a pose JSON file or use --restore.")
    try:
        result = apply(args.pid, args.client_dir, args.pose, args.stormlib_module)
    except (AttributeError, ImportError, IndexError, KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"Live dance update failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
