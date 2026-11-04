"""Route two dancers' replicated emotes in an isolated 12340 observer client."""

import argparse
import ctypes
from ctypes import wintypes
from hashlib import sha256
import json
from pathlib import Path
import struct

if __package__:
    from . import client_poc, duet_assets, runtime_poc
else:
    import client_poc
    import duet_assets
    import runtime_poc


IMAGE_BASE = 0x400000
HOOK = 0x717244
ORIGINAL = bytes.fromhex("8b 40 08 8b 4d 0c 89 01")
OVERWRITE = 6
CONNECTION = 0xC79CE0
OBJECT_MANAGER = 0x2ED0
ACTIVE_GUID = 0xC0
PAGE = 0x1000
MEM_IMAGE = 0x1000000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PROCESS_READ_RIGHTS = 0x0410  # Query information and read process memory.
SELECTOR_SIGNATURE = b"WoWDUET1"
SELECTOR_STATE = struct.Struct("<8sQIIQII")
FIRST_COUNTER = struct.calcsize("<8sQI")
ACTOR_STATE_SIZE = struct.calcsize("<QII")
MARKER = "WoWSpotlight duet lab"
SLOTS = {client_poc.ANIMATION_ID, duet_assets.SECOND_ANIMATION_ID}


def near_jump(source, target):
    return b"\xe9" + struct.pack("<I", (target - source - 5) & 0xFFFFFFFF)


def selector_code(address, actors):
    # EAX is the Emotes.dbc row. ECX points to the object's GUID descriptor.
    # Preserve flags and leave the original registers and output intact except
    # when a configured actor selects a stock dance (row 10).
    code = bytearray.fromhex("9c 83 38 0a 75 00")  # pushfd; cmp [eax], 10; jne fallback
    fallback_jumps = [len(code) - 1]
    code += bytes.fromhex("83 78 08 45 74 09")  # cmp [eax+8], 69; je match_actor
    code += bytes.fromhex("81 78 08 d3 00 00 00 75 00")  # cmp [eax+8], 211; jne fallback
    fallback_jumps.append(len(code) - 1)
    finish_jumps = []
    for index, (guid, animation) in enumerate(actors):
        counter = address + PAGE + FIRST_COUNTER + ACTOR_STATE_SIZE * index
        code += b"\x81\x39" + struct.pack("<I", guid & 0xFFFFFFFF) + b"\x75\x00"
        next_actor = [len(code) - 1]
        code += b"\x81\x79\x04" + struct.pack("<I", guid >> 32) + b"\x75\x00"
        next_actor.append(len(code) - 1)
        code += b"\xb8" + struct.pack("<I", animation)
        code += b"\xf0\xff\x05" + struct.pack("<I", counter) + b"\xeb\x00"
        for jump in next_actor:
            code[jump] = len(code) - jump - 1
        finish_jumps.append(len(code) - 1)

    for jump in fallback_jumps:
        code[jump] = len(code) - jump - 1
    code += ORIGINAL[:3]  # Use the stock animation for all other emotes and actors.
    for jump in finish_jumps:
        code[jump] = len(code) - jump - 1
    code += b"\x9d" + ORIGINAL[3:OVERWRITE]
    code += near_jump(address + len(code), HOOK + OVERWRITE)
    return bytes(code)


def read_exact(process, address, size):
    data = process.read(address, size)
    if data is None:
        raise OSError(f"Could not read the observer at 0x{address:08X}.")
    return data


def read_u32(process, address):
    return struct.unpack("<I", read_exact(process, address, 4))[0]


def object_manager(process):
    connection = read_u32(process, CONNECTION)
    return read_u32(process, connection + OBJECT_MANAGER) if connection else 0


def active_guid(process):
    manager = object_manager(process)
    return struct.unpack("<Q", read_exact(process, manager + ACTIVE_GUID, 8))[0] if manager else 0


def lookup_unit(process, manager, guid):
    # This is the read-only form of the client's GUID lookup at 0x4D4BB0.
    if not manager:
        return 0
    mask = read_u32(process, manager + 0x24)
    if mask == 0xFFFFFFFF:
        return 0
    buckets = read_u32(process, manager + 0x1C)
    if not buckets or mask >= 2**20 or mask & (mask + 1):
        raise ValueError("The object manager's bucket table changed.")
    low = guid & 0xFFFFFFFF
    bucket = buckets + 12 * (low & mask)
    link, _, unit = struct.unpack("<III", read_exact(process, bucket, 12))
    for _ in range(256):
        if not unit or unit & 1:
            return 0
        if (read_u32(process, unit + 0x18) == low
                and struct.unpack("<Q", read_exact(process, unit + 0x30, 8))[0] == guid):
            return unit
        unit = read_u32(process, (unit + link + 4) & 0xFFFFFFFF)
    raise ValueError("The object manager's bucket did not terminate.")


def actor_snapshot(process, manager, guid):
    unit = lookup_unit(process, manager, guid)
    if not unit:
        return {"loaded": False}
    model = read_u32(process, unit + 0xB4)
    fields = read_u32(process, unit + 0xD0)
    emote = read_u32(process, fields + 0x134) if fields else None
    state = read_u32(process, model + 0x94) if model else 0
    result = {"loaded": True, "emote_state": emote, "model": f"0x{model:08X}" if model else None}
    if state:
        # CM2Model::GetAnimation(-1) at 0x8266B0 reads base state record 0.
        data = read_exact(process, state, 0x98)
        animation = struct.unpack_from("<I", data, 0x90)[0]
        sequence = struct.unpack_from("<H", data, 0x48)[0]
        result.update(active_animation=None if animation == 0xFFFFFFFF else animation,
                      active_sequence_index=None if sequence == 0xFFFF else sequence)
    if struct.unpack("<Q", read_exact(process, unit + 0x30, 8))[0] != guid:
        raise ValueError("The actor changed while reading its animation.")
    return result


def inspect_selector(process):
    site = read_exact(process, HOOK, len(ORIGINAL))
    if site == ORIGINAL:
        return None
    if site[:1] != b"\xe9" or site[5:] != b"\x90" + ORIGINAL[OVERWRITE:]:
        raise ValueError("The client's emote resolver has unexpected instructions.")
    address = (HOOK + 5 + struct.unpack_from("<i", site, 1)[0]) & 0xFFFFFFFF
    state = read_exact(process, address + PAGE, SELECTOR_STATE.size)
    signature, guid_a, slot_a, hits_a, guid_b, slot_b, hits_b = SELECTOR_STATE.unpack(state)
    actors = ((guid_a, slot_a), (guid_b, slot_b))
    if signature != SELECTOR_SIGNATURE or not valid_actors(actors):
        raise ValueError("The emote resolver points to an unrecognized selector.")
    code = selector_code(address, actors)
    if read_exact(process, address, len(code)) != code:
        raise ValueError("The installed duet selector does not match this prototype.")
    return {"installed": True, "actors": [
        {"guid": f"0x{guid:016X}", "animation": slot, "selection_hits": hits}
        for (guid, slot), hits in zip(actors, (hits_a, hits_b))
    ]}


def bind(kernel, name, result, *arguments):
    function = getattr(kernel, name)
    function.restype = result
    function.argtypes = arguments
    return function


def checked(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def install(process, actors, kernel):
    previous = inspect_selector(process)
    if previous is not None:
        installed = tuple((int(actor["guid"], 16), actor["animation"]) for actor in previous["actors"])
        if actors == installed:
            return previous
        raise ValueError("Restart the observer client before changing its dancer assignments.")
    if active_guid(process):
        raise ValueError("Log the observer out to character selection before installing the selector.")

    handle, pointer, size, word, flag = (
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.BOOL,
    )
    allocate = bind(kernel, "VirtualAllocEx", pointer, handle, pointer, size, word, word)
    release = bind(kernel, "VirtualFreeEx", flag, handle, pointer, size, word)
    protect = bind(kernel, "VirtualProtectEx", flag, handle, pointer, size, word, ctypes.POINTER(word))
    flush = bind(kernel, "FlushInstructionCache", flag, handle, pointer, size)
    address = checked(allocate(process.handle, None, 2 * PAGE,
                               runtime_poc.MEM_COMMIT | MEM_RESERVE, runtime_poc.PAGE_READWRITE))
    try:
        if address + 2 * PAGE > 2**32:
            raise ValueError("The observer did not allocate memory in its 32-bit address space.")
        code = selector_code(address, actors)
        (guid_a, slot_a), (guid_b, slot_b) = actors
        state = SELECTOR_STATE.pack(SELECTOR_SIGNATURE, guid_a, slot_a, 0, guid_b, slot_b, 0)
        process.write(address + PAGE, state)
        process.write(address, code)
        old = word()
        checked(protect(process.handle, address, PAGE, PAGE_EXECUTE_READ, ctypes.byref(old)))
        checked(flush(process.handle, address, len(code)))
        if (read_exact(process, address, len(code)) != code
                or read_exact(process, address + PAGE, len(state)) != state):
            raise OSError("The observer did not retain the duet selector.")
        if active_guid(process) or read_exact(process, HOOK, len(ORIGINAL)) != ORIGINAL:
            raise ValueError("The observer entered the world or its resolver changed during setup.")

        branch = near_jump(HOOK, address) + b"\x90"
        checked(protect(process.handle, HOOK, OVERWRITE, PAGE_EXECUTE_READWRITE, ctypes.byref(old)))
        try:
            process.write(HOOK, branch)
            checked(flush(process.handle, HOOK, OVERWRITE))
            result = inspect_selector(process)
            if result is None:
                raise OSError("The observer did not retain the selector branch.")
        except (OSError, ValueError):
            process.write(HOOK, ORIGINAL[:OVERWRITE])
            checked(flush(process.handle, HOOK, OVERWRITE))
            raise
        finally:
            unused = word()
            checked(protect(process.handle, HOOK, OVERWRITE, old.value, ctypes.byref(unused)))
    except (OSError, ValueError):
        # Keep the allocation if the branch might still be live after a failed rollback.
        if process.read(HOOK, len(ORIGINAL)) == ORIGINAL:
            release(process.handle, address, 0, MEM_RELEASE)
        raise
    return result


def install_once(process, pid, actors):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    mutex = bind(kernel, "CreateMutexW", wintypes.HANDLE,
                 ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    ctypes.set_last_error(0)
    handle = checked(mutex(None, True, f"Local\\WoWSpotlight-Duet-{pid}"))
    already_exists = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    try:
        if already_exists:
            raise ValueError("A duet setup is already running for this observer.")
        return install(process, actors, kernel)
    finally:
        if not already_exists:
            bind(kernel, "ReleaseMutex", wintypes.BOOL, wintypes.HANDLE)(handle)
        process.close(handle)


def valid_actors(actors):
    return (len(actors) == 2 and len({guid for guid, _ in actors}) == 2
            and all(0 < guid < 2**64 for guid, _ in actors)
            and {slot for _, slot in actors} == SLOTS)


def parse_actor(value):
    try:
        guid, slot = value.split("=", 1)
        return int(guid, 0), int(slot, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use a dancer GUID and decimal slot, e.g. 0x1234=211.") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    for command in ("install", "status"):
        action = subcommands.add_parser(command)
        action.add_argument("pid", type=int, help="PID of the isolated duet WoW.exe")
        action.add_argument("--client-dir", type=Path, required=True)
        if command == "install":
            action.add_argument("--actor", type=parse_actor, action="append", required=True,
                                help="Dancer GUID=slot. Supply one dancer for each slot, 211 and 154.")
    args = parser.parse_args()
    client_dir = args.client_dir.resolve()
    executable = client_dir / "WoW.exe"
    try:
        if client_dir == client_poc.DEFAULT_DATA.resolve().parent:
            raise ValueError("Select the isolated duet observer copy.")
        if (client_dir / "SpotlightDuet.lab").read_text(encoding="ascii").strip() != MARKER:
            raise ValueError("The selected client is missing the duet lab marker.")
        if sha256(executable.read_bytes()).hexdigest() != runtime_poc.CLIENT_HASH:
            raise ValueError("The executable does not match the verified 3.3.5a lab build.")
        if args.action == "install":
            actors = tuple(sorted(args.actor))
            if not valid_actors(actors):
                raise ValueError("Supply two distinct dancer GUIDs and one assignment per duet slot.")
            if not (client_dir / "Data" / "patch-Z.MPQ").is_file():
                raise ValueError("Install the duet animation patch in the isolated observer first.")
        rights = runtime_poc.PROCESS_RIGHTS if args.action == "install" else PROCESS_READ_RIGHTS
        with runtime_poc.ClientProcess(args.pid, executable, rights=rights) as process:
            region = runtime_poc.MemoryRegion()
            if (not process.query_region(process.handle, HOOK, ctypes.byref(region), ctypes.sizeof(region))
                    or region.allocation_base != IMAGE_BASE or region.type != MEM_IMAGE
                    or read_exact(process, IMAGE_BASE, 2) != b"MZ"):
                raise ValueError("The observer's executable is not mapped at the verified address.")
            result = install_once(process, args.pid, actors) if args.action == "install" else inspect_selector(process)
            result = result or {"installed": False}
            result["local_player_guid"] = f"0x{active_guid(process):016X}"
            if args.action == "status" and result["installed"]:
                manager = object_manager(process)
                for actor in result["actors"]:
                    try:
                        actor.update(actor_snapshot(process, manager, int(actor["guid"], 16)))
                    except (OSError, ValueError) as error:
                        actor.update(loaded=None, snapshot_error=str(error))
        print(json.dumps(result, indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Duet selector failed: {error}\n")


if __name__ == "__main__":
    main()
