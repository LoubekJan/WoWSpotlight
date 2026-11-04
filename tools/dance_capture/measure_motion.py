"""Measure tracking gaps and local rotation stability on matching Spotlight captures."""

import argparse
from bisect import bisect_left, bisect_right
import importlib.util
import json
import math
from pathlib import Path
import struct

if __package__:
    from . import client_poc
else:
    import client_poc


CORE = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
LEGS = (7, 8, 14, 15, 20, 22)
FEET = {"left": ((27, 29, 31), (1, 3, 7, 14, 20, 32)),
        "right": ((28, 30, 32), (1, 3, 8, 15, 22, 33))}
CONFIDENCE = 0.35
SLOT_MS = 17_700


def percentile(values, percent):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    index = math.floor(position)
    fraction = position - index
    return round(ordered[index] * (1 - fraction) + ordered[math.ceil(position)] * fraction, 4)


def dot(first, second):
    return sum(a * b for a, b in zip(first, second))


def geodesic(first, second):
    """Smallest angle between unit rotations, ignoring quaternion sign."""
    return math.degrees(2 * math.acos(min(1.0, abs(dot(first, second)))))


def interpolate(first, second, fraction):
    cosine = dot(first, second)
    if cosine < 0:
        second = tuple(-value for value in second)
        cosine = -cosine
    if cosine > 0.9999:
        return client_poc.normalized(tuple(a + (b - a) * fraction for a, b in zip(first, second)))
    angle = math.acos(cosine)
    weights = math.sin((1 - fraction) * angle) / math.sin(angle), math.sin(fraction * angle) / math.sin(angle)
    return tuple(weights[0] * a + weights[1] * b for a, b in zip(first, second))


def local_jitter(times, rotations, bones):
    errors = []
    for bone in bones:
        keys = rotations[bone]
        for index in range(1, len(times) - 1):
            fraction = (times[index] - times[index - 1]) / (times[index + 1] - times[index - 1])
            predicted = interpolate(keys[index - 1], keys[index + 1], fraction)
            errors.append(geodesic(keys[index], predicted))
    return percentile(errors, 95)


def largest_angle(angles):
    bone = max(angles, key=angles.__getitem__)
    return {"degrees": round(angles[bone], 4), "bone": bone}


def motion_metrics(clip, assets=None, planted=None):
    if clip.get("format") != client_poc.FULL_BODY_FORMAT:
        raise ValueError("Expected a full-body Spotlight motion JSON.")
    times, rotations = client_poc.full_body_motion(clip, SLOT_MS)
    report = {
        "frames": len(times),
        "duration_ms": times[-1],
        "rotation_midpoint_error_p95_deg": {
            "all": local_jitter(times, rotations, rotations),
            "head": local_jitter(times, rotations, (16,)),
            "forearms": local_jitter(times, rotations, (30, 31)),
            "legs": local_jitter(times, rotations, LEGS),
        },
        "capture_endpoint_angle_max": largest_angle({
            bone: geodesic(keys[0], keys[-1]) for bone, keys in rotations.items()
        }),
    }
    if assets is not None:
        model, source = assets
        baked, _ = client_poc.bake_clip(model, source, clip)
        report["native_endpoint_angle_max"] = baked_seam(model, baked)
        if planted is not None:
            report["projected_contact_proxy"] = contact_metrics(model, times, rotations, planted)
    return report


def baked_seam(model, animation):
    def key_at(offset):
        return client_poc.normalized(tuple(
            value + 32768 if value < 0 else value - 32767
            for value in client_poc.QUATERNION.unpack_from(animation, offset)
        ))

    angles = {}
    for bone, track in client_poc.full_body_tracks(model, animation).items():
        end = track.key_offset + (len(track.timestamps) - 1) * client_poc.QUATERNION.size
        angles[bone] = geodesic(key_at(track.key_offset), key_at(end))
    return largest_angle(angles)


def pose_metrics(pose):
    if pose.get("format") != "mediapipe-pose-landmarks" or pose.get("version") != 1:
        raise ValueError("Expected a version 1 MediaPipe pose JSON.")
    frames = pose["frames"]
    if len(frames) < 2:
        raise ValueError("The pose requires at least two frames.")
    times = [frame["time_ms"] for frame in frames]
    if (any(type(time) is not int for time in times) or times[0] != 0
            or any(b <= a for a, b in zip(times, times[1:]))):
        raise ValueError("Pose times must increase in milliseconds starting at zero.")
    gaps = {}
    for landmark in CORE + (29, 30, 31, 32):
        observed = []
        for time, frame in zip(times, frames):
            if frame["pose"] is None:
                continue
            point = frame["pose"]["world"][landmark]
            if all(math.isfinite(value) for value in point) and min(point[3:]) >= CONFIDENCE:
                observed.append(time)
        anchors = [times[0], *observed, times[-1]]
        gaps[landmark] = {
            "low_or_missing_frames": len(times) - len(observed),
            "max_observation_gap_ms": max(b - a for a, b in zip(anchors, anchors[1:])),
        }
    return {
        "frames": len(times),
        "missing_pose_frames": sum(frame["pose"] is None for frame in frames),
        "confidence_threshold": CONFIDENCE,
        "landmarks": gaps,
    }


def planted_samples(pose):
    """Find low, locally still foot observations in a stationary camera view."""
    times = [frame["time_ms"] for frame in pose["frames"]]
    image = [frame["pose"].get("image") if frame["pose"] is not None else None for frame in pose["frames"]]

    def position(points, index):
        if points is None:
            return None
        x, y, z, visibility, presence = points[index]
        if (all(math.isfinite(value) for value in (x, y, z, visibility, presence))
                and 0 <= x <= 1 and 0 <= y <= 1 and min(visibility, presence) >= 0.55):
            return x, y
        return None

    def center(first, second):
        return tuple((a + b) / 2 for a, b in zip(first, second))

    scales = []
    for points in image:
        shoulders_hips = tuple(position(points, index) for index in (11, 12, 23, 24))
        if all(shoulders_hips):
            scales.append(math.dist(center(*shoulders_hips[:2]), center(*shoulders_hips[2:])))
    scale = percentile(scales, 50)
    if not scale:
        return {side: [] for side in FEET}

    samples = {}
    for side, ((_, heel, toe), _) in FEET.items():
        feet = [tuple(position(points, index) for index in (heel, toe)) for points in image]
        valid = [bool(heel and toe) for heel, toe in feet]
        levels = [center(*foot)[1] if okay else None for okay, foot in zip(valid, feet)]
        contact = set()
        for index, time in enumerate(times):
            if not valid[index]:
                continue
            nearby = range(bisect_left(times, time - 85), bisect_right(times, time + 85))
            neighbors = [candidate for candidate in nearby if valid[candidate]]
            if len(neighbors) < 3:
                continue
            displacement = max(math.dist(point, other) for candidate in neighbors
                               for point, other in zip(feet[index], feet[candidate]))
            if displacement > 0.045 * scale:
                continue
            around = range(bisect_left(times, time - 350), bisect_right(times, time + 350))
            floor = max(levels[candidate] for candidate in around if valid[candidate])
            if levels[index] >= floor - 0.12 * scale:
                contact.add(index)
        samples[side] = [(times[index - 1], times[index]) for index in sorted(contact)
                         if index - 1 in contact and times[index] - times[index - 1] <= 100]
    return samples


def multiply(first, second):
    x, y, z, w = first
    a, b, c, d = second
    return (w * a + x * d + y * c - z * b, w * b - x * c + y * d + z * a,
            w * c + x * b - y * a + z * d, w * d - x * a - y * b - z * c)


def contact_metrics(model, times, rotations, planted):
    frame_index = {time: index for index, time in enumerate(times)}
    bone_offset = struct.unpack_from("<I", model, 48)[0]
    pivots = {bone: struct.unpack_from("<3f", model, bone_offset + bone * 88 + 76)
              for _, chain in FEET.values() for bone in chain}

    def foot_positions(chain, index):
        orientation = (0, 0, 0, 1)
        position = pivots[chain[0]]
        for parent, child in zip(chain, chain[1:]):
            orientation = multiply(orientation, rotations[parent][index])
            delta = tuple(b - a for a, b in zip(pivots[parent], pivots[child]))
            inverse = tuple(-value for value in orientation[:3]) + (orientation[3],)
            offset = multiply(multiply(orientation, (*delta, 0)), inverse)
            position = tuple(a + b for a, b in zip(position, offset))
            if child == chain[-2]:
                ankle = position
        return ankle, position

    result = {}
    for side, (_, chain) in FEET.items():
        intervals = [(frame_index[first], frame_index[second]) for first, second in planted[side]
                     if first in frame_index and second in frame_index]
        indices = {index for pair in intervals for index in pair}
        positions = {index: foot_positions(chain, index) for index in indices}
        result[side] = {"intervals": len(intervals)}
        for joint, index in (("ankle", 0), ("toe", 1)):
            result[side][f"{joint}_step_p95_model_units"] = percentile([
                math.dist(positions[first][index], positions[second][index]) for first, second in intervals
            ], 95)
    return result


def load_assets(client_data, wrapper):
    spec = importlib.util.spec_from_file_location("spotlight_quality_stormlib", wrapper)
    if spec is None or spec.loader is None:
        raise ImportError("Pass the path to the StormLib Python wrapper.")
    stormlib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stormlib)
    return (
        client_poc.read_source(stormlib.Archive, client_data / "patch-3.MPQ",
                               client_poc.MODEL_PATH, client_poc.MODEL_HASH),
        client_poc.read_source(stormlib.Archive, client_data / "patch-2.MPQ",
                               client_poc.ANIMATION_PATH, client_poc.ANIMATION_HASH),
    )


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=("Compare matching captures. Intentional changes can raise midpoint errors. "
                "The contact proxy uses projected stillness, so it assumes a fixed camera and has no floor truth."),
    )
    parser.add_argument("motion", nargs="+", type=Path, help="One or more full-body motion JSONs")
    parser.add_argument("--pose", type=Path, help="Original MediaPipe pose JSON for confidence-gap diagnostics")
    parser.add_argument("--client-data", type=Path, help="Verified WoW Data directory to also measure the baked seam")
    parser.add_argument("--stormlib-module", type=Path, default=client_poc.DEFAULT_STORMLIB)
    args = parser.parse_args()
    try:
        assets = load_assets(args.client_data, args.stormlib_module) if args.client_data else None
        report = {}
        planted = None
        if args.pose:
            pose = read_json(args.pose)
            report["pose"] = pose_metrics(pose)
            if assets is not None:
                planted = planted_samples(pose)
        report["motion"] = {str(path): motion_metrics(read_json(path), assets, planted) for path in args.motion}
    except (AttributeError, ImportError, IndexError, KeyError, OSError, TypeError, ValueError, struct.error) as error:
        parser.exit(1, f"Motion quality measurement failed: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
