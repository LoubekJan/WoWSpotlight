"""Bake two or three distinct HumanMale animation slots into a test-client MPQ."""

import argparse
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory

if __package__:
    from . import client_poc
    from .preview_poc import LOGIN_SCRIPT
else:
    import client_poc
    from preview_poc import LOGIN_SCRIPT


SECOND_ANIMATION_ID = 154  # Custom1 in AnimationData.dbc, unused by this HumanMale.
SECOND_ANIMATION_PATH = r"Character\Human\Male\HumanMale0154-00.anim"
THIRD_ANIMATION_ID = 155  # Custom2 in AnimationData.dbc, also unused.
THIRD_ANIMATION_PATH = r"Character\Human\Male\HumanMale0155-00.anim"
SLOT_MEMBERS = {
    client_poc.ANIMATION_ID: client_poc.ANIMATION_PATH,
    SECOND_ANIMATION_ID: SECOND_ANIMATION_PATH,
}
UNIFIED_SLOT_MEMBERS = {**SLOT_MEMBERS, THIRD_ANIMATION_ID: THIRD_ANIMATION_PATH}
SEQUENCES = 28
SEQUENCE_LOOKUP = 36
SEQUENCE_SIZE = 64
ARRAY = struct.Struct("<2I")
UINT16 = struct.Struct("<H")

# Header array offset, record stride and relative track offsets in this Wrath M2.
# An event track contains timestamps only. All other tracks have two M2Arrays.
TRACKS = (
    (44, 88, (16, 36, 56), 2),  # Bones
    (72, 40, (0, 20), 2),       # Colors
    (88, 20, (0,), 2),          # Texture weights
    (96, 60, (0, 20, 40), 2),   # Texture transforms
    (240, 40, (20,), 2),        # Attachments
    (256, 36, (24,), 1),        # Events
    (272, 100, (16, 48, 80), 2),  # Cameras
)


def append_aligned(model, payload):
    model.extend(bytes(-len(model) % 16))
    offset = len(model)
    model.extend(payload)
    return offset


def slot_footer(slot):
    # The footer is beyond all M2 track offsets and identifies a loaded .anim
    # even if both slots currently contain exactly the same motion.
    return sha256(f"WoWSpotlight duet slot {slot}".encode("ascii")).digest()


def duplicate_slot(model, *, third=False):
    if sha256(model).hexdigest() != client_poc.MODEL_HASH:
        raise ValueError("Use the verified 12340 HumanMale model.")

    sequence_count, sequence_offset = ARRAY.unpack_from(model, SEQUENCES)
    lookup_count, lookup_offset = ARRAY.unpack_from(model, SEQUENCE_LOOKUP)
    original_index = UINT16.unpack_from(model, lookup_offset + client_poc.ANIMATION_ID * 2)[0]
    extra_slots = (SECOND_ANIMATION_ID, THIRD_ANIMATION_ID) if third else (SECOND_ANIMATION_ID,)
    new_sequence_count = sequence_count + len(extra_slots)
    start = sequence_offset + original_index * SEQUENCE_SIZE
    result = bytearray(model)
    new_sequence_offset = append_aligned(result, model[sequence_offset:sequence_offset + sequence_count * SEQUENCE_SIZE])
    for sequence_index, slot in enumerate(extra_slots, start=sequence_count):
        lookup_entry = lookup_offset + slot * 2
        if slot >= lookup_count or UINT16.unpack_from(model, lookup_entry)[0] != 0xFFFF:
            raise ValueError(f"The animation lookup for slot {slot} is not empty.")
        duplicate = bytearray(model[start:start + SEQUENCE_SIZE])
        UINT16.pack_into(duplicate, 0, slot)
        UINT16.pack_into(duplicate, 62, sequence_index)  # The sequence aliases only itself.
        result.extend(duplicate)
        UINT16.pack_into(result, lookup_entry, sequence_index)
    ARRAY.pack_into(result, SEQUENCES, new_sequence_count, new_sequence_offset)

    for header, stride, track_offsets, array_count in TRACKS:
        record_count, offset = ARRAY.unpack_from(model, header)
        for index in range(record_count):
            for track_offset in track_offsets:
                track = offset + index * stride + track_offset
                for array_index in range(array_count):
                    array = track + 4 + array_index * ARRAY.size
                    count, start = ARRAY.unpack_from(model, array)
                    if count <= 1:
                        continue  # Empty or shared across all sequences.
                    if count != sequence_count:
                        raise ValueError("Unexpected per-sequence track array size.")
                    entry = start + original_index * ARRAY.size
                    descriptor = model[entry:entry + ARRAY.size]
                    descriptors = model[start:start + count * ARRAY.size] + descriptor * len(extra_slots)
                    new_offset = append_aligned(result, descriptors)
                    ARRAY.pack_into(result, array, new_sequence_count, new_offset)
    return bytes(result)


def preview_login(archive_type, client_data):
    with archive_type(client_data / "enUS" / "patch-enUS-3.MPQ") as archive:
        login = archive.read(LOGIN_SCRIPT)
    sequence = f"\r\nlocal duetSequenceA, duetSequenceB = {client_poc.ANIMATION_ID}, {SECOND_ANIMATION_ID}\r\n"
    return login + sequence.encode("ascii") + Path(__file__).with_name("duet_preview.lua").read_bytes()


def build_duet(archive_type, client_data, first_clip, second_clip, output, *, preview=False, third_clip=None):
    model = client_poc.read_source(archive_type, client_data / "patch-3.MPQ",
                                   client_poc.MODEL_PATH, client_poc.MODEL_HASH)
    animation = client_poc.read_source(archive_type, client_data / "patch-2.MPQ",
                                       client_poc.ANIMATION_PATH, client_poc.ANIMATION_HASH)
    has_third = third_clip is not None
    members = {client_poc.MODEL_PATH: duplicate_slot(model, third=has_third)}
    slot_members = UNIFIED_SLOT_MEMBERS if has_third else SLOT_MEMBERS
    clip_paths = (first_clip, second_clip, third_clip) if has_third else (first_clip, second_clip)
    report = {}
    for (slot, member), clip_path in zip(slot_members.items(), clip_paths, strict=True):
        clip = json.loads(clip_path.read_text(encoding="utf-8"))
        baked, stats = client_poc.bake_clip(model, animation, clip)
        members[member] = baked + slot_footer(slot)
        report[slot] = {**stats, "member": member, "animation_sha256": sha256(baked).hexdigest()}
    if preview:
        members[LOGIN_SCRIPT] = preview_login(archive_type, client_data)

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as work:
        staged = Path(work) / output.name
        with archive_type(staged, create=True, capacity=8) as archive:
            for member, contents in members.items():
                archive.write(member, contents)
        with archive_type(staged) as archive:
            for member, contents in members.items():
                if archive.read(member) != contents:
                    raise ValueError(f"The written member could not be verified: {member}.")
        staged.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first_clip", type=Path, help="Clip for slot 211")
    parser.add_argument("second_clip", type=Path, help="Clip for slot 154")
    parser.add_argument("output", type=Path, help="New test MPQ outside the client")
    parser.add_argument("--third-clip", type=Path, help="Optional clip for slot 155")
    parser.add_argument("--preview", action="store_true", help="Include the offline login-screen preview in the MPQ")
    parser.add_argument("--client-data", type=Path, default=client_poc.DEFAULT_DATA)
    parser.add_argument("--stormlib-module", type=Path, default=client_poc.DEFAULT_STORMLIB)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.suffix.lower() != ".mpq" or output.exists():
        parser.error("Use the path to a new .MPQ file.")
    if any(output.is_relative_to(data.resolve().parent) for data in (args.client_data, client_poc.DEFAULT_DATA)):
        parser.error("Build the patch outside the client and install it only on a test copy.")

    try:
        spec = spec_from_file_location("spotlight_stormlib", args.stormlib_module)
        if spec is None or spec.loader is None:
            raise ImportError("Pass the path to the StormLib Python wrapper.")
        stormlib = module_from_spec(spec)
        spec.loader.exec_module(stormlib)
        report = build_duet(stormlib.Archive, args.client_data, args.first_clip, args.second_clip, output,
                            preview=args.preview, third_clip=args.third_clip)
    except (ImportError, KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"Duet MPQ generation failed: {error}\n")
    print(json.dumps({"archive": str(output), "slots": report}, indent=2))


if __name__ == "__main__":
    main()
