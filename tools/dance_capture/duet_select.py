"""Route two dancers' replicated emotes in an isolated 12340 observer client."""

import argparse
import ctypes
from ctypes import wintypes
from hashlib import sha256
import json
from pathlib import Path
import struct
import time

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
ANIMATE = 0x71FD80
ANIMATE_ORIGINAL = bytes.fromhex("55 8b ec 83 ec 40")
UPDATE_BASE = 0x73AC30
UPDATE_BASE_PREFIX = bytes.fromhex("55 8b ec 56 8b f1 8b 8e")
SEEK_SEQUENCE = 0x826ED0
SEEK_SEQUENCE_PREFIX = bytes.fromhex("55 8b ec 83 ec 08 56 8b")
GET_TICK_COUNT = 0x9DF174  # Kernel32 import of the verified client.
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
SELECTOR_SIGNATURE = b"WoWDUET2"
GENERATION = len(SELECTOR_SIGNATURE)
BANKS = 0x20
BANK = struct.Struct("<QIIQII")
ANIMATE_CODE = 0x200
REQUEST = 0x80
REQUEST_DATA = struct.Struct("<QIIII")
PENDING, RUNNING, APPLIED, SKIPPED = range(1, 5)
REQUEST_TTL_MS = 500
SLOT_DURATION_MS = 17_700
MARKER = "WoWSpotlight duet lab"
SLOT_ORDER = (client_poc.ANIMATION_ID, duet_assets.SECOND_ANIMATION_ID)
SLOTS = set(SLOT_ORDER)


def near_jump(source, target):
    return b"\xe9" + struct.pack("<I", (target - source - 5) & 0xFFFFFFFF)


class Code:
    def __init__(self, address):
        self.address = address
        self.data = bytearray()
        self.labels = {}
        self.branches = []

    def add(self, encoded, operand=None):
        self.data.extend(bytes.fromhex(encoded))
        if operand is not None:
            self.data.extend(struct.pack("<I", operand))

    def label(self, label):
        self.labels[label] = len(self.data)

    def branch(self, opcode, label):
        self.add(opcode)
        self.branches.append((len(self.data), label))
        self.data.extend(bytes(4))

    def external(self, opcode, target):
        self.add(opcode)
        self.data.extend(struct.pack("<I", (target - self.address - len(self.data) - 4) & 0xFFFFFFFF))

    def finish(self):
        for offset, label in self.branches:
            struct.pack_into("<i", self.data, offset, self.labels[label] - offset - 4)
        return bytes(self.data)


def selector_code(address):
    # EAX is the Emotes.dbc row. ECX points to the object's GUID descriptor.
    # Preserve flags and leave the original registers and output intact except
    # when a configured actor selects a stock dance (row 10).
    code = Code(address)
    code.add("9c 53 52 56 83 38 0a")  # save flags and registers; cmp [eax], 10
    code.branch("0f 85", "fallback")
    code.add("83 78 08 45")  # cmp [eax+8], 69
    code.branch("0f 84", "actors")
    code.add("81 78 08", client_poc.ANIMATION_ID)
    code.branch("0f 85", "fallback")
    code.label("actors")
    state = address + PAGE
    code.add("8b 1d", state + GENERATION)  # mov ebx, [generation]
    code.add(f"89 da 83 e2 01 6b d2 {BANK.size:02x}")  # edx = (ebx & 1) * bank size
    code.add("81 c2", state + BANKS)
    for index, animation in enumerate(SLOT_ORDER):
        record = index * 16
        next_actor = f"next{index}"
        code.add(f"8b 31 3b 72 {record:02x}")  # GUID low
        code.branch("0f 85", next_actor)
        code.add(f"8b 71 04 3b 72 {record + 4:02x}")  # GUID high
        code.branch("0f 85", next_actor)
        code.add(f"80 7a {record + 8:02x} 01")  # enabled entry
        code.branch("0f 85", next_actor)
        code.add("3b 1d", state + GENERATION)
        code.branch("0f 85", "fallback")
        code.add("b8", animation)
        code.add(f"f0 ff 42 {record + 12:02x}")  # increment bank counter
        code.branch("e9", "done")
        code.label(next_actor)

    code.label("fallback")
    code.data.extend(ORIGINAL[:3])
    code.label("done")
    code.add("5e 5a 5b 9d")
    code.data.extend(ORIGINAL[3:OVERWRITE])
    code.external("e9", HOOK + OVERWRITE)
    return code.finish()


def animate_code(address):
    """Consume one phase request in the client's own unit animation callback."""
    code = Code(address + ANIMATE_CODE)
    request = address + PAGE + REQUEST
    guid = request + 4
    code.add("9c 60")  # pushfd; pushad
    code.add("83 3d", request)
    code.add("01")  # cmp [state], pending
    code.branch("0f 85", "done")
    code.add("89 ce")  # mov esi, ecx (unit)
    code.add("ff 15", GET_TICK_COUNT)
    code.add("2b 05", guid + 16)  # subtract submission tick
    code.add("3d", REQUEST_TTL_MS)
    code.branch("0f 87", "expired")
    code.add("89 c3")  # preserve elapsed across native calls
    code.add("a1", address + PAGE + GENERATION)
    code.add("3b 05", guid + 20)  # only requests for the published assignment bank
    code.branch("0f 85", "expired")
    code.add("8b 4e 08 85 c9")  # read unit descriptor
    code.branch("0f 84", "done")
    code.add("8b 01 3b 05", guid)
    code.branch("0f 85", "done")
    code.add("8b 41 04 3b 05", guid + 4)
    code.branch("0f 85", "done")
    code.add("b8", PENDING)
    code.add("ba", RUNNING)
    code.add("f0 0f b1 15", request)  # lock cmpxchg [state], edx
    code.branch("0f 85", "done")
    code.add("8b 86 d0 00 00 00 85 c0")  # native unit descriptor (emote)
    code.branch("0f 84", "skipped")
    code.add("83 b8 34 01 00 00 0a")  # replicated emote must still be dance
    code.branch("0f 85", "skipped")
    code.add("8b 3d", guid + 8)  # expected animation

    for retry in (False, True):
        code.add("8b 8e b4 00 00 00 85 c9")  # ECX = current world model
        code.branch("0f 84", "skipped")
        code.add("f6 41 10 01")  # model must be loaded
        code.branch("0f 84", "skipped")
        code.add("8b 81 94 00 00 00 85 c0")  # EAX = base model bone state
        code.branch("0f 84", "skipped")
        code.add("39 b8 90 00 00 00")  # cmp [bone+sequenceId], edi
        if retry:
            code.branch("0f 85", "skipped")
        else:
            code.branch("0f 84", "seek")
            code.add("6a ff 6a 00 89 f1")  # unit->UpdateBaseAnimation(0, -1)
            code.external("e8", UPDATE_BASE)

    code.label("seek")
    code.add("66 83 78 48 ff")  # base sequence index must be resolved
    code.branch("0f 84", "skipped")
    code.add("a1", address + PAGE + GENERATION)
    code.add("3b 05", guid + 20)
    code.branch("0f 85", "skipped")
    code.add("a1", guid + 12)
    code.add("01 d8 3d", SLOT_DURATION_MS)
    code.branch("0f 82", "phase")
    code.add("2d", SLOT_DURATION_MS)
    code.label("phase")
    code.add("50 6a ff")  # model->SetBoneSequenceTime(-1, phase)
    code.external("e8", SEEK_SEQUENCE)
    code.add("c7 05", request)
    code.add("03 00 00 00")
    code.branch("e9", "done")
    code.label("skipped")
    code.add("c7 05", request)
    code.add("04 00 00 00")
    code.branch("e9", "done")
    code.label("expired")
    code.add("b8", PENDING)
    code.add("ba", SKIPPED)
    code.add("f0 0f b1 15", request)
    code.label("done")
    code.add("61 9d")
    code.data.extend(ANIMATE_ORIGINAL)
    code.external("e9", ANIMATE + len(ANIMATE_ORIGINAL))
    return code.finish()


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


def unit_emote(process, unit):
    fields = read_u32(process, unit + 0xD0) if unit else 0
    if not fields:
        return None, None
    # UNIT_NPC_EMOTESTATE and the stand-state byte of UNIT_FIELD_BYTES_1.
    return read_u32(process, fields + 0x134), read_u32(process, fields + 0x110) & 0xFF


def actor_snapshot(process, manager, guid):
    unit = lookup_unit(process, manager, guid)
    if not unit:
        return {"loaded": False}
    model = read_u32(process, unit + 0xB4)
    emote, stand = unit_emote(process, unit)
    state = read_u32(process, model + 0x94) if model else 0
    result = {"loaded": True, "emote_state": emote, "stand_state": stand,
              "model": f"0x{model:08X}" if model else None}
    if state:
        # CM2Model::GetAnimation(-1) at 0x8266B0 reads base state record 0.
        data = read_exact(process, state, 0x98)
        animation = struct.unpack_from("<I", data, 0x90)[0]
        sequence = struct.unpack_from("<H", data, 0x48)[0]
        result.update(active_animation=None if animation == 0xFFFFFFFF else animation,
                      active_sequence_index=None if sequence == 0xFFFF else sequence)
        if animation in SLOTS:
            scene = read_u32(process, model + 0x28)
            if scene:
                scene_ms = read_u32(process, scene + 0x0C)
                start_ms, speed, start_offset = struct.unpack_from("<I4xf4xI", data, 0x4C)
                if speed == 1.0:
                    result["phase_ms"] = (((scene_ms - start_ms) & 0xFFFFFFFF) + start_offset) % SLOT_DURATION_MS
    if struct.unpack("<Q", read_exact(process, unit + 0x30, 8))[0] != guid:
        raise ValueError("The actor changed while reading its animation.")
    return result


def selector_address(process):
    site = read_exact(process, HOOK, len(ORIGINAL))
    timing_site = read_exact(process, ANIMATE, len(ANIMATE_ORIGINAL))
    if site == ORIGINAL and timing_site == ANIMATE_ORIGINAL:
        return None
    if site[:1] != b"\xe9" or site[5:] != b"\x90" + ORIGINAL[OVERWRITE:]:
        raise ValueError("The client's emote resolver has unexpected instructions.")
    address = (HOOK + 5 + struct.unpack_from("<i", site, 1)[0]) & 0xFFFFFFFF
    if read_exact(process, address + PAGE, len(SELECTOR_SIGNATURE)) != SELECTOR_SIGNATURE:
        raise ValueError("The emote resolver points to an unrecognized selector.")
    code = selector_code(address)
    if read_exact(process, address, len(code)) != code:
        raise ValueError("The installed duet selector does not match this prototype.")
    timing_address = address + ANIMATE_CODE
    timing_code = animate_code(address)
    if (timing_site != near_jump(ANIMATE, timing_address) + b"\x90"
            or read_exact(process, timing_address, len(timing_code)) != timing_code):
        raise ValueError("The installed duet timing hook does not match this prototype.")
    return address


def bank_address(state, generation):
    return state + BANKS + (generation & 1) * BANK.size


def pack_bank(actors):
    by_slot = {slot: guid for guid, slot in actors}
    values = [value for slot in SLOT_ORDER for value in (by_slot.get(slot, 0), int(slot in by_slot), 0)]
    return BANK.pack(*values)


def read_bank(process, state):
    generation = read_u32(process, state + GENERATION)
    entries = BANK.unpack(read_exact(process, bank_address(state, generation), BANK.size))
    if read_u32(process, state + GENERATION) != generation:
        raise ValueError("The duet assignments changed during the read.")
    actors = []
    for index, slot in enumerate(SLOT_ORDER):
        guid, enabled, hits = entries[index * 3:index * 3 + 3]
        if enabled not in (0, 1) or bool(guid) != bool(enabled):
            raise ValueError("The installed duet assignments are invalid.")
        if enabled:
            actors.append((guid, slot, hits))
    if not valid_actors((guid, slot) for guid, slot, _ in actors):
        raise ValueError("The installed duet assignments are invalid.")
    return generation, actors


def inspect_selector(process):
    address = selector_address(process)
    if address is None:
        return None
    _, actors = read_bank(process, address + PAGE)
    return {"installed": True, "actors": [
        {"guid": f"0x{guid:016X}", "animation": slot, "selection_hits": hits}
        for guid, slot, hits in actors
    ]}


def configure(process, actors):
    """Publish the complete mapping from the companion's single writer."""
    actors = tuple(actors)
    if not valid_actors(actors):
        raise ValueError("Supply at most two distinct dancer GUIDs and use each duet slot once.")
    address = selector_address(process)
    if address is None:
        raise ValueError("Install the duet selector before setting its assignments.")
    state = address + PAGE
    generation, previous = read_bank(process, state)
    if set(actors) == {(guid, slot) for guid, slot, _ in previous}:
        return inspect_selector(process)
    next_generation = (generation + 1) & 0xFFFFFFFF
    staged = bank_address(state, next_generation)
    payload = pack_bank(actors)
    process.write(staged, payload)
    if read_exact(process, staged, BANK.size) != payload or read_u32(process, state + GENERATION) != generation:
        raise ValueError("The observer did not retain the staged duet assignments.")
    # One aligned DWORD publishes the inactive bank, so readers never see a partial GUID.
    process.write(state + GENERATION, struct.pack("<I", next_generation))
    if read_u32(process, state + GENERATION) != next_generation:
        raise ValueError("The observer did not publish the duet assignments.")
    return inspect_selector(process)


def sync_actor(process, manager, guid, expected_slot, phase_ms):
    """Reselect and seek an active native dance on the game thread, once per request."""
    if expected_slot not in SLOTS | {69} or type(phase_ms) is not int or not 0 <= phase_ms < SLOT_DURATION_MS:
        raise ValueError("Pass a duet slot and a phase within the native dance loop.")
    if actor_snapshot(process, manager, guid).get("emote_state") != 10:
        return False
    address = selector_address(process)
    if address is None:
        raise ValueError("Install the duet selector before synchronizing an actor.")
    state = address + PAGE
    generation, actors = read_bank(process, state)
    active = {actor_guid: slot for actor_guid, slot, _ in actors}
    if active.get(guid, 69) != expected_slot:
        raise ValueError("The actor is not assigned to the requested dance slot.")

    request = state + REQUEST
    if read_u32(process, request) in (PENDING, RUNNING):
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    tick_count = bind(kernel, "GetTickCount", wintypes.DWORD)
    process.write(request + 4, REQUEST_DATA.pack(guid, expected_slot, phase_ms, tick_count(), generation))
    process.write(request, struct.pack("<I", PENDING))
    deadline = time.monotonic() + 0.15
    while time.monotonic() < deadline:
        status = read_u32(process, request)
        if status == APPLIED:
            return True
        if status == SKIPPED:
            return False
        time.sleep(0.01)
    return False


def bind(kernel, name, result, *arguments):
    function = getattr(kernel, name)
    function.restype = result
    function.argtypes = arguments
    return function


def checked(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def patch_site(process, protect, flush, address, original, replacement):
    if read_exact(process, address, len(original)) != original:
        raise ValueError(f"The instructions changed at 0x{address:08X} during duet setup.")
    old = wintypes.DWORD()
    checked(protect(process.handle, address, len(original), PAGE_EXECUTE_READWRITE, ctypes.byref(old)))
    try:
        process.write(address, replacement)
        checked(flush(process.handle, address, len(original)))
        if read_exact(process, address, len(replacement)) != replacement:
            raise OSError(f"The observer did not retain the branch at 0x{address:08X}.")
    except (OSError, ValueError):
        process.write(address, original)
        checked(flush(process.handle, address, len(original)))
        raise
    finally:
        unused = wintypes.DWORD()
        checked(protect(process.handle, address, len(original), old.value, ctypes.byref(unused)))


def install(process, actors, kernel):
    previous = inspect_selector(process)
    if previous is not None:
        return configure(process, actors)
    if active_guid(process):
        raise ValueError("Log the observer out to character selection before installing the selector.")
    if (read_exact(process, UPDATE_BASE, len(UPDATE_BASE_PREFIX)) != UPDATE_BASE_PREFIX
            or read_exact(process, SEEK_SEQUENCE, len(SEEK_SEQUENCE_PREFIX)) != SEEK_SEQUENCE_PREFIX
            or not read_u32(process, GET_TICK_COUNT)):
        raise ValueError("The observer's native animation functions do not match this build.")

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
        code = selector_code(address)
        timing_code = animate_code(address)
        if len(code) > ANIMATE_CODE or ANIMATE_CODE + len(timing_code) > PAGE:
            raise ValueError("The duet instructions no longer fit their executable page.")
        state = SELECTOR_SIGNATURE.ljust(BANKS, b"\0") + pack_bank(actors) + bytes(BANK.size)
        process.write(address + PAGE, state)
        process.write(address, code)
        process.write(address + ANIMATE_CODE, timing_code)
        old = word()
        checked(protect(process.handle, address, PAGE, PAGE_EXECUTE_READ, ctypes.byref(old)))
        checked(flush(process.handle, address, PAGE))
        if (read_exact(process, address, len(code)) != code
                or read_exact(process, address + ANIMATE_CODE, len(timing_code)) != timing_code
                or read_exact(process, address + PAGE, len(state)) != state):
            raise OSError("The observer did not retain the duet selector.")
        if active_guid(process) or selector_address(process) is not None:
            raise ValueError("The observer entered the world or its resolver changed during setup.")

        patches = (
            (HOOK, ORIGINAL[:OVERWRITE], near_jump(HOOK, address) + b"\x90"),
            (ANIMATE, ANIMATE_ORIGINAL, near_jump(ANIMATE, address + ANIMATE_CODE) + b"\x90"),
        )
        installed = []
        try:
            for site, original, replacement in patches:
                patch_site(process, protect, flush, site, original, replacement)
                installed.append((site, replacement, original))
            result = inspect_selector(process)
            if result is None:
                raise OSError("The observer did not retain both duet hooks.")
        except (OSError, ValueError):
            for site, replacement, original in reversed(installed):
                patch_site(process, protect, flush, site, replacement, original)
            raise
    except (OSError, ValueError):
        # Keep the allocation if the branch might still be live after a failed rollback.
        if (process.read(HOOK, len(ORIGINAL)) == ORIGINAL
                and process.read(ANIMATE, len(ANIMATE_ORIGINAL)) == ANIMATE_ORIGINAL):
            release(process.handle, address, 0, MEM_RELEASE)
        raise
    return result


def install_once(process, pid, actors=()):
    actors = tuple(actors)
    if not valid_actors(actors):
        raise ValueError("Supply at most two distinct dancer GUIDs and use each duet slot once.")
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
    actors = tuple(actors)
    return (len(actors) <= 2 and len({guid for guid, _ in actors}) == len(actors)
            and all(0 < guid < 2**64 for guid, _ in actors)
            and len({slot for _, slot in actors}) == len(actors)
            and all(slot in SLOTS for _, slot in actors))


def parse_actor(value):
    try:
        guid, slot = value.split("=", 1)
        return int(guid, 0), int(slot, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use a dancer GUID and decimal slot, e.g. 0x1234=211.") from error


def verified_executable(client_dir):
    client_dir = Path(client_dir).resolve()
    if client_dir == client_poc.DEFAULT_DATA.resolve().parent:
        raise ValueError("Select the isolated duet client copy.")
    executable = client_dir / "WoW.exe"
    if sha256(executable.read_bytes()).hexdigest() != runtime_poc.CLIENT_HASH:
        raise ValueError("The executable does not match the verified 3.3.5a lab build.")
    return executable


def verify_image(process):
    region = runtime_poc.MemoryRegion()
    if (not process.query_region(process.handle, HOOK, ctypes.byref(region), ctypes.sizeof(region))
            or region.allocation_base != IMAGE_BASE or region.type != MEM_IMAGE
            or read_exact(process, IMAGE_BASE, 2) != b"MZ"):
        raise ValueError("The client's executable is not mapped at the verified address.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    for command in ("install", "status"):
        action = subcommands.add_parser(command)
        action.add_argument("pid", type=int, help="PID of the isolated duet WoW.exe")
        action.add_argument("--client-dir", type=Path, required=True)
        if command == "install":
            action.add_argument("--actor", type=parse_actor, action="append", default=[],
                                help="Dancer GUID=slot. Optional, with up to one dancer per slot 211 or 154.")
    args = parser.parse_args()
    client_dir = args.client_dir.resolve()
    try:
        executable = verified_executable(client_dir)
        if args.action == "install":
            if (client_dir / "SpotlightDuet.lab").read_text(encoding="ascii").strip() != MARKER:
                raise ValueError("The selected client is missing the duet lab marker.")
            actors = tuple(sorted(args.actor))
            if not valid_actors(actors):
                raise ValueError("Supply at most two distinct dancer GUIDs and use each duet slot once.")
            if not (client_dir / "Data" / "patch-Z.MPQ").is_file():
                raise ValueError("Install the duet animation patch in the isolated observer first.")
        rights = runtime_poc.PROCESS_RIGHTS if args.action == "install" else PROCESS_READ_RIGHTS
        with runtime_poc.ClientProcess(args.pid, executable, rights=rights) as process:
            verify_image(process)
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
