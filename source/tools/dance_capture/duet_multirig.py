"""Build independent, fixed-length Spotlight animation slots on the stock Wrath rigs."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import struct
from tempfile import TemporaryDirectory

if __package__:
    from . import client_poc, duet_assets, spotlight_rigs
else:
    import client_poc
    import duet_assets
    import spotlight_rigs


LOCAL_SLOT = spotlight_rigs.LOCAL_SLOT
SLOTS = (LOCAL_SLOT, duet_assets.SECOND_ANIMATION_ID, duet_assets.THIRD_ANIMATION_ID)
DURATION_MS = 17_700
KEY_COUNT = 426
MANIFEST_MEMBER = r"Spotlight\rigs.json"
MANIFEST = b'{"version":1,"slots":[156,154,155]}\n'

# Highest-priority stock MPQ members from the verified enUS build 12340 data.
SOURCE_MODELS = {
    "HumanMale": ("patch-3", client_poc.MODEL_HASH),
    "HumanFemale": ("patch-3", "e16307402e19a1c1c00bd34aced3237432ad593d3c64a512f716808e65cbe0dc"),
    "OrcMale": ("patch-3", "76097ce5227249cf02064686f146721211a0a08864ff1e97a92424fd9775d703"),
    "OrcFemale": ("patch-2", "78c58cab2984baf4c66818b80b62a73e8e304a6ce56da46268a12f2a5784ddcf"),
    "DwarfMale": ("patch-3", "a101ecf6737323bde80317c11f59f8eba3fae63b76a5e77ade059a23499e0969"),
    "DwarfFemale": ("patch-3", "b97620d055cd1d026a777c1cc99e53ea501e5e3af81ce1b4cea5a97c64dd1c15"),
    "NightElfMale": ("patch-3", "7a952dcce6bf1f8e1adf065788676fc213ec1a631dc88316836c9b693e408185"),
    "NightElfFemale": ("patch-3", "33ca943dc11a49774bc57f1398a81ba6f813c6233770005cdcb1b1c33e14c1eb"),
    "ScourgeMale": ("patch-2", "a40783df61b12b0e053bd21fc5a930ae37cc649423b79e2f4b076e048fe2a220"),
    "ScourgeFemale": ("patch-3", "7fad09f9df13b990509522406b6a7f0b4e87d4bfef989a934260260a88e3d582"),
    "TaurenMale": ("patch-3", "339347aa26e246ec4f72563a92a3c470d3ef876ab728e17b5b38b0888e04a680"),
    "TaurenFemale": ("patch-3", "c74b71a5b08e4047e43f7090219e324d3c8f8d58c0b273725070ae282e7d4d07"),
    "GnomeMale": ("patch-2", "881a0ca662d89de5aee76a12ad5846aa34d04bba57f0f502d7eb5a242538d320"),
    "GnomeFemale": ("patch-2", "642f8ed75265426d0c2260352304fc157d5a7bcb1a3b6689776f875edf7ac525"),
    "TrollMale": ("patch-3", "c15577e13fed4683ad662a08566fa2b5007f219115ef40613b9c58f5bdefb8b9"),
    "TrollFemale": ("patch-3", "2994330c193085cc801ab9722ee7c3adb151ca62c1bbb572a2c437058996152b"),
    "BloodElfMale": ("patch-3", "9ecb63d46a6c1068fc35e3bae554102cd24d712e816d561867d4dffe48bd5aa4"),
    "BloodElfFemale": ("patch-3", "37c8e03e551e3020a74e249b8c7858c4c30a66a113f3733c615aac636280a5ed"),
    "DraeneiMale": ("patch-3", "f1c55747f6eab053448fa4e29cf9e43a829156171baeb9a23c177b7f19dc147a"),
    "DraeneiFemale": ("patch-3", "ae0e44434f002cff2186b664c43fee217e0c47500ffb488d83a52523f8ef6201"),
}


@dataclass(frozen=True)
class Rig:
    model: bytes
    stock: bytes
    tracks: dict[int, client_poc.RotationTrack]
    translations: tuple[tuple[int, int], ...] = ()


def animation_member(model_name, slot):
    return spotlight_rigs.model_path(model_name).removesuffix(".m2") + f"{slot:04d}-00.anim"


def slot_footer(model_name, slot):
    return sha256(f"WoWSpotlight rig v1 {model_name} slot {slot}".encode("ascii")).digest()


def read_model(archive_type, client_data, model_name):
    archive, digest = SOURCE_MODELS[model_name]
    return client_poc.read_source(archive_type, Path(client_data) / f"{archive}.MPQ",
                                  spotlight_rigs.model_path(model_name), digest)


def is_multirig(archive):
    try:
        contents = archive.read(MANIFEST_MEMBER)
    except OSError as error:
        if error.errno == 2:
            return False
        raise
    if contents != MANIFEST:
        raise ValueError("Use a Spotlight archive matching this multi-rig runtime.")
    return True


def make_rig(model_name, model):
    if sha256(model).hexdigest() != SOURCE_MODELS[model_name][1]:
        raise ValueError(f"Expected the verified {model_name} model.")
    mapped = spotlight_rigs.bone_map(model, model_name)
    if set(mapped) != set(client_poc.FULL_BODY_BONES) or len(set(mapped.values())) != len(mapped):
        raise ValueError(f"Incomplete or duplicate dance bones in {model_name}.")

    sequence_count, sequence_offset = duet_assets.ARRAY.unpack_from(model, duet_assets.SEQUENCES)
    lookup_count, lookup_offset = duet_assets.ARRAY.unpack_from(model, duet_assets.SEQUENCE_LOOKUP)
    sequences = bytearray(model[sequence_offset:sequence_offset + sequence_count * duet_assets.SEQUENCE_SIZE])
    dance_index = duet_assets.UINT16.unpack_from(model, lookup_offset + 69 * 2)[0]
    if not 0 <= dance_index < sequence_count:
        raise ValueError(f"Missing original dance in {model_name}.")
    # Reuse the model's dance bounds and apply the same external, looping flags as the old HumanMale slot.
    bounds_offset = dance_index * duet_assets.SEQUENCE_SIZE + 32
    bounds = sequences[bounds_offset:bounds_offset + 28]
    patched = bytearray(model)
    for sequence_index, slot in enumerate(SLOTS, start=sequence_count):
        lookup_entry = lookup_offset + slot * 2
        if slot >= lookup_count or duet_assets.UINT16.unpack_from(model, lookup_entry)[0] != 0xFFFF:
            raise ValueError(f"The animation lookup for slot {slot} is not empty in {model_name}.")
        sequences.extend(struct.pack("<HHIfIhHIII28shH", slot, 0, DURATION_MS, 0, 0, 32767,
                                     0, 0, 0, 150, bounds, -1, sequence_index))
        duet_assets.UINT16.pack_into(patched, lookup_entry, sequence_index)
    new_sequence_count = sequence_count + len(SLOTS)
    new_sequence_offset = duet_assets.append_aligned(patched, sequences)
    duet_assets.ARRAY.pack_into(patched, duet_assets.SEQUENCES, new_sequence_count, new_sequence_offset)

    timestamps = tuple(round(index * DURATION_MS / (KEY_COUNT - 1)) for index in range(KEY_COUNT))
    times = struct.pack(f"<{KEY_COUNT}I", *timestamps)
    identity = bytearray(client_poc.QUATERNION.size)
    client_poc.pack_rotation(identity, 0, (0, 0, 0, 1))
    keys = identity * KEY_COUNT
    animation = bytearray()
    tracks = {}
    for bone in sorted(mapped.values()):
        time_offset = duet_assets.append_aligned(animation, times)
        key_offset = duet_assets.append_aligned(animation, keys)
        tracks[bone] = client_poc.RotationTrack(timestamps, time_offset, key_offset)

    for header, stride, track_offsets, array_count in duet_assets.TRACKS:
        record_count, offset = duet_assets.ARRAY.unpack_from(model, header)
        for index in range(record_count):
            for track_offset in track_offsets:
                track = offset + index * stride + track_offset
                rotation = tracks.get(index) if header == 44 and track_offset == 36 else None
                if rotation:
                    interpolation, global_sequence = struct.unpack_from("<Hh", model, track)
                    if interpolation not in (0, 1) or global_sequence != -1:
                        raise ValueError(f"Unexpected dance rotation track {index} in {model_name}.")
                    duet_assets.UINT16.pack_into(patched, track, 1)
                for array_index in range(array_count):
                    array = track + 4 + array_index * duet_assets.ARRAY.size
                    count, start = duet_assets.ARRAY.unpack_from(model, array)
                    if count <= 1 and not rotation:
                        continue  # Empty tracks or tracks shared across sequences stay as-is.
                    if count != sequence_count and not (rotation and count == 0):
                        raise ValueError(f"Unexpected per-sequence track array size in {model_name}.")
                    if rotation and interpolation == 0 and count:
                        raise ValueError(f"Dance rotation would change stock interpolation in {model_name}.")
                    original = (model[start:start + count * duet_assets.ARRAY.size] if count
                                else bytes(sequence_count * duet_assets.ARRAY.size))
                    added = duet_assets.ARRAY.pack(0, 0)
                    if rotation:
                        data_offset = rotation.key_offset if array_index else rotation.time_offset
                        added = duet_assets.ARRAY.pack(KEY_COUNT, data_offset)
                    new_offset = duet_assets.append_aligned(patched, original + added * len(SLOTS))
                    duet_assets.ARRAY.pack_into(patched, array, new_sequence_count, new_offset)
    return bytes(patched), Rig(model, bytes(animation), tracks)


def load_rig(archive, model_name, source_model):
    model, rig = make_rig(model_name, source_model)
    if archive.read(spotlight_rigs.model_path(model_name)) != model:
        raise ValueError(f"The Spotlight archive contains an unexpected {model_name} model.")
    for slot in SLOTS:
        if archive.read(animation_member(model_name, slot)) != rig.stock + slot_footer(model_name, slot):
            raise ValueError(f"The Spotlight archive contains an unexpected {model_name} slot {slot}.")
    return rig


def build_multirig(archive_type, client_data, output):
    members = {MANIFEST_MEMBER: MANIFEST}
    report = {}
    for model_name in spotlight_rigs.PLAYABLE_MODELS:
        source = read_model(archive_type, client_data, model_name)
        model, rig = make_rig(model_name, source)
        members[spotlight_rigs.model_path(model_name)] = model
        for slot in SLOTS:
            members[animation_member(model_name, slot)] = rig.stock + slot_footer(model_name, slot)
        report[model_name] = {"slots": SLOTS, "rotation_tracks": len(rig.tracks)}

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as work:
        staged = Path(work) / output.name
        with archive_type(staged, create=True, capacity=128) as archive:
            for member, contents in members.items():
                archive.write(member, contents)
        with archive_type(staged) as archive:
            for member, contents in members.items():
                if archive.read(member) != contents:
                    raise ValueError(f"The written member could not be verified: {member}.")
        staged.rename(output)
    return report
