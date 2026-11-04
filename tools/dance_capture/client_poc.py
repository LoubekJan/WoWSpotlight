"""Build an isolated 3.3.5a Human Male dance patch from extracted pose JSON."""

import argparse
from bisect import bisect_right
from dataclasses import dataclass
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import math
from pathlib import Path
import struct
from tempfile import TemporaryDirectory

if __package__:
    from .arm_motion import extract_right_forearm_motion
else:
    from arm_motion import extract_right_forearm_motion


MODEL_PATH = r"Character\Human\Male\HumanMale.m2"
ANIMATION_PATH = r"Character\Human\Male\HumanMale0211-00.anim"
MODEL_HASH = "b22478c1ab8d1e9bb7542f686e60e4e665a510d11b5360109a3e9e46d5bf91d2"
ANIMATION_HASH = "aecd3eb3aa03b617c5da716e0e853adb95776ffcdf5874570c65b4f162e91910"
DEFAULT_DATA = Path(r"C:\WoWModding\Client-Lab\Data")
DEFAULT_STORMLIB = Path(__file__).resolve().with_name("stormlib.py")
EMOTE_ID = 400
ANIMATION_ID = 211
RIGHT_ARM = 18
RIGHT_FOREARM = 31
RIGHT_HAND = 38
QUATERNION = struct.Struct("<4h")
FULL_BODY_BONES = (1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18, 20, 22, 30, 31, 36, 38)
FULL_BODY_FORMAT = "wow-spotlight-motion"


@dataclass(frozen=True)
class RotationTrack:
    timestamps: tuple[int, ...]
    time_offset: int
    key_offset: int

    def ranges(self):
        count = len(self.timestamps)
        return (self.time_offset, self.time_offset + count * 4), (self.key_offset, self.key_offset + count * QUATERNION.size)


def read_source(archive_type, path, member, expected_hash):
    with archive_type(path) as archive:
        data = archive.read(member)
    if sha256(data).hexdigest() != expected_hash:
        raise ValueError(f"Unexpected source for {member} in {path.name}. Use the verified 12340 lab assets.")
    return data


def track_arrays(model, bone, track_offset):
    lookup_offset = struct.unpack_from("<I", model, 40)[0]
    sequence_index = struct.unpack_from("<H", model, lookup_offset + ANIMATION_ID * 2)[0]
    bone_offset = struct.unpack_from("<I", model, 48)[0]
    offset = bone_offset + bone * 88 + track_offset
    interpolation, global_sequence, time_count, time_table, key_count, key_table = struct.unpack_from(
        "<Hh4I", model, offset
    )
    if interpolation != 1 or global_sequence != -1 or sequence_index >= min(time_count, key_count):
        return None
    return (struct.unpack_from("<2I", model, time_table + sequence_index * 8),
            struct.unpack_from("<2I", model, key_table + sequence_index * 8))


def rotation_track(model, animation, bone):
    arrays = track_arrays(model, bone, 36)
    if arrays is None:
        raise ValueError(f"Unexpected rotation track layout for bone {bone}.")
    (time_count, time_offset), (key_count, key_offset) = arrays
    if time_count != key_count or time_count < 2 or key_offset + key_count * QUATERNION.size > len(animation):
        raise ValueError(f"The animation is missing rotation keys for bone {bone}.")
    timestamps = struct.unpack_from(f"<{time_count}I", animation, time_offset)
    if timestamps[0] != 0 or any(a >= b for a, b in zip(timestamps, timestamps[1:])):
        raise ValueError(f"Unexpected rotation timestamps for bone {bone}.")
    return RotationTrack(timestamps, time_offset, key_offset)


def full_body_tracks(model, animation):
    return {bone: rotation_track(model, animation, bone) for bone in FULL_BODY_BONES}


def translation_ranges(model):
    ranges = []
    for bone in (1, RIGHT_HAND):
        arrays = track_arrays(model, bone, 16)
        if arrays is None:
            raise ValueError(f"Unexpected translation track layout for bone {bone}.")
        _, (count, offset) = arrays
        ranges.append((offset, offset + count * 12))
    return ranges


def forearm_track(model, animation):
    track = rotation_track(model, animation, RIGHT_FOREARM)
    bone_offset = struct.unpack_from("<I", model, 48)[0]

    shoulder, elbow, wrist = (
        struct.unpack_from("<3f", model, bone_offset + index * 88 + 76)
        for index in (RIGHT_ARM, RIGHT_FOREARM, RIGHT_HAND)
    )
    x, y, z = (end - start for start, end in zip(elbow, wrist))
    u, v, w = (end - start for start, end in zip(elbow, shoulder))
    # Rotate the rest forearm toward the shoulder when the captured elbow bends.
    axis = (y * w - z * v, z * u - x * w, x * v - y * u)
    return track.timestamps, track.key_offset, normalized(axis)


def normalized(values):
    length = math.hypot(*values)
    return tuple(value / length for value in values)


def pack_rotation(output, offset, rotation):
    quantized = [round(value * 32767) + (32767 if value <= 0 else -32768) for value in rotation]
    QUATERNION.pack_into(output, offset, *quantized)


def flex_forearm(model, animation, motion):
    timestamps, offset, (x, y, z) = forearm_track(model, animation)
    components = QUATERNION.unpack_from(animation, offset)
    base_x, base_y, base_z, base_w = normalized(tuple(
        (value + 32768 if value < 0 else value - 32767) / 32767 for value in components
    ))
    motion_times, motion_angles = zip(*motion)
    if motion_times[-1] <= motion_times[0]:
        raise ValueError("Capture at least two distinct motion timestamps.")
    if motion_times[-1] > timestamps[-1]:
        raise ValueError(f"Use a clip that fits the {timestamps[-1] / 1000:g}-second animation slot.")

    output = bytearray(animation)
    for index, timestamp in enumerate(timestamps):
        # Keep the source timing, then hold the last captured pose to the end of the slot.
        right = bisect_right(motion_times, timestamp)
        if right == 0:
            angle = motion_angles[0]
        elif right == len(motion_times):
            angle = motion_angles[-1]
        else:
            left = right - 1
            progress = (timestamp - motion_times[left]) / (motion_times[right] - motion_times[left])
            angle = motion_angles[left] + progress * (motion_angles[right] - motion_angles[left])

        sine = math.sin(angle / 2)
        bend_x, bend_y, bend_z, bend_w = x * sine, y * sine, z * sine, math.cos(angle / 2)
        rotation = (
            base_w * bend_x + base_x * bend_w + base_y * bend_z - base_z * bend_y,
            base_w * bend_y - base_x * bend_z + base_y * bend_w + base_z * bend_x,
            base_w * bend_z + base_x * bend_y - base_y * bend_x + base_z * bend_w,
            base_w * bend_w - base_x * bend_x - base_y * bend_y - base_z * bend_z,
        )
        pack_rotation(output, offset + index * QUATERNION.size, rotation)
    return bytes(output), len(timestamps), timestamps[-1]


def full_body_motion(clip, duration_ms):
    if clip.get("version") != 1 or clip.get("model") != "HumanMale":
        raise ValueError("Expected version 1 Spotlight motion for HumanMale.")
    if type(clip.get("loop", False)) is not bool:
        raise ValueError("Spotlight motion loop must be true or false.")
    frames = clip["frames"]
    if not 2 <= len(frames) <= 1800:
        raise ValueError("Spotlight motion requires 2 to 1,800 frames.")
    times = []
    rotations = {bone: [] for bone in FULL_BODY_BONES}
    bone_ids = {str(bone) for bone in FULL_BODY_BONES}
    for frame in frames:
        timestamp = frame["time_ms"]
        if type(timestamp) is not int or not 0 <= timestamp <= duration_ms or (times and timestamp <= times[-1]):
            raise ValueError(f"Motion timestamps must increase within the {duration_ms / 1000:g}-second slot.")
        times.append(timestamp)
        frame_rotations = frame["rotations"]
        if set(frame_rotations) != bone_ids:
            raise ValueError("Each frame must include exactly the supported HumanMale bones.")
        for bone, keys in rotations.items():
            rotation = frame_rotations[str(bone)]
            if len(rotation) != 4 or any(type(value) not in (float, int) or not math.isfinite(value) for value in rotation):
                raise ValueError(f"Bone {bone} needs four finite quaternion components.")
            if not math.isclose(math.hypot(*rotation), 1, abs_tol=0.01):
                raise ValueError(f"Bone {bone} needs a unit quaternion.")
            rotation = normalized(rotation)
            if keys and sum(a * b for a, b in zip(keys[-1], rotation)) < 0:
                rotation = tuple(-value for value in rotation)
            keys.append(rotation)
    if times[0] != 0:
        raise ValueError("Spotlight motion must start at 0 ms.")
    return times, rotations


def mix_rotation(start, end, fraction):
    if sum(a * b for a, b in zip(start, end)) < 0:
        end = tuple(-value for value in end)
    return normalized(tuple(a + fraction * (b - a) for a, b in zip(start, end)))


def rotation_sample(times, rotations, timestamp):
    right = bisect_right(times, timestamp)
    if right == len(times):
        return rotations[-1]
    left = right - 1
    fraction = (timestamp - times[left]) / (times[right] - times[left])
    return mix_rotation(rotations[left], rotations[right], fraction)


def smoothstep(fraction):
    return fraction * fraction * (3 - 2 * fraction)


def loop_sample(times, rotations, timestamp, slot_duration):
    end = times[-1]
    blend = min(300, max(1, end // 4))
    period = min(end + blend, slot_duration)
    phase = timestamp % period
    # Start smoothly from the same pose at which the previous cycle closed.
    ease = min(80, end // 5)
    if phase < ease:
        progress = phase / ease
        sample_time = phase * progress * (2 - progress)
    else:
        sample_time = min(phase, end)
    rotation = rotation_sample(times, rotations, sample_time)
    if phase > period - blend:
        rotation = mix_rotation(rotation, rotations[0], smoothstep((phase - period + blend) / blend))

    # If the native slot ends during a partial cycle, close that cycle too.
    final_blend = min(blend, slot_duration % period)
    if timestamp > slot_duration - final_blend:
        rotation = mix_rotation(rotation, rotations[0], smoothstep((timestamp - slot_duration + final_blend) / final_blend))
    return rotation


def bake_full_body(model, animation, clip):
    tracks = full_body_tracks(model, animation)
    duration_ms = tracks[RIGHT_FOREARM].timestamps[-1]
    times, rotations = full_body_motion(clip, duration_ms)
    clip_end = times[-1]
    loop = clip.get("loop", False)
    output = bytearray(animation)
    for bone, track in tracks.items():
        count = len(track.timestamps)
        if loop:
            baked_times = [round(index * duration_ms / (count - 1)) for index in range(count)]
        else:
            # Existing captures keep their original cadence and last-pose hold.
            capture_count = min(count - (clip_end < duration_ms), clip_end + 1)
            hold_count = count - capture_count
            baked_times = [round(index * clip_end / (capture_count - 1)) for index in range(capture_count)]
            baked_times.extend(clip_end + round(index * (duration_ms - clip_end) / hold_count)
                               for index in range(1, hold_count + 1))
        struct.pack_into(f"<{count}I", output, track.time_offset, *baked_times)
        previous = None
        for index, timestamp in enumerate(baked_times):
            rotation = (loop_sample(times, rotations[bone], timestamp, duration_ms) if loop
                        else rotation_sample(times, rotations[bone], timestamp))
            if loop and previous is not None and sum(a * b for a, b in zip(previous, rotation)) < 0:
                rotation = tuple(-value for value in rotation)
            previous = rotation
            pack_rotation(output, track.key_offset + index * QUATERNION.size, rotation)
    # A rotation-only capture uses the bind translation for the moving root and hand.
    for start, end in translation_ranges(model):
        output[start:end] = bytes(end - start)
    return bytes(output), {"rotation_tracks": len(tracks), "rotation_keys": sum(len(t.timestamps) for t in tracks.values()),
                           "slot_duration_ms": duration_ms, "capture_keys": len(times), "capture_duration_ms": clip_end,
                           "loop": loop}


def bake_clip(model, animation, clip):
    if clip.get("format") == FULL_BODY_FORMAT:
        return bake_full_body(model, animation, clip)
    motion = extract_right_forearm_motion(clip)
    patched, keys, duration_ms = flex_forearm(model, animation, motion)
    return patched, {"forearm_keys": keys, "slot_duration_ms": duration_ms, "capture_keys": len(motion),
                     "capture_duration_ms": motion[-1][0] - motion[0][0]}


def build_patch(archive_type, data_path, pose_path, output_path):
    with pose_path.open(encoding="utf-8") as stream:
        clip = json.load(stream)
    model = read_source(archive_type, data_path / "patch-3.MPQ", MODEL_PATH, MODEL_HASH)
    animation = read_source(archive_type, data_path / "patch-2.MPQ", ANIMATION_PATH, ANIMATION_HASH)
    patched, stats = bake_clip(model, animation, clip)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_path.parent) as directory:
        staged = Path(directory) / output_path.name
        with archive_type(staged, create=True, capacity=8) as archive:
            archive.write(ANIMATION_PATH, patched)
        with archive_type(staged) as archive:
            if archive.read(ANIMATION_PATH) != patched:
                raise ValueError("The written patch did not match its input animation.")
        staged.rename(output_path)
    return {"archive": str(output_path), "member": ANIMATION_PATH, "emote": EMOTE_ID,
            **stats,
            "changed_bytes": sum(a != b for a, b in zip(animation, patched)),
            "animation_sha256": sha256(patched).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pose", type=Path, help="Spotlight motion or MediaPipe pose JSON")
    parser.add_argument("output", type=Path, help="New .MPQ file outside the game client")
    parser.add_argument("--client-data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--stormlib-module", type=Path, default=DEFAULT_STORMLIB)
    args = parser.parse_args()
    output_path = args.output.resolve()
    data_path = args.client_data.resolve()
    if output_path.suffix.lower() != ".mpq" or output_path.exists():
        parser.error("Use the path to a new .MPQ file.")
    if any(output_path.is_relative_to(client) for client in (data_path.parent, DEFAULT_DATA.resolve().parent)):
        parser.error("Write the patch outside the client. Install it separately on a test copy.")

    try:
        spec = spec_from_file_location("dance_stormlib", args.stormlib_module)
        if spec is None or spec.loader is None:
            raise ImportError("Pass the path to the StormLib Python wrapper.")
        stormlib = module_from_spec(spec)
        spec.loader.exec_module(stormlib)
        report = build_patch(stormlib.Archive, data_path, args.pose, output_path)
    except (AttributeError, ImportError, IndexError, KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"Dance patch failed: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
