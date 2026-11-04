"""Measure right forearm flexion in a dance capture."""

import argparse
import json
import math
from pathlib import Path


RIGHT_ARM = (12, 14, 16)  # Shoulder, elbow, wrist.
MIN_CONFIDENCE = 0.5
MIN_COVERAGE = 0.8
MAX_GAP_MS = 250


def elbow_flexion(pose):
    if pose is None:
        return None

    points = [pose["world"][index] for index in RIGHT_ARM]
    for point in points:
        x, y, z, visibility, presence = point
        if not all(math.isfinite(value) for value in (x, y, z, visibility, presence)):
            raise ValueError("Arm landmarks must contain finite numbers.")
        if min(visibility, presence) < MIN_CONFIDENCE:
            return None

    shoulder, elbow, wrist = (point[:3] for point in points)
    upper = [joint - start for start, joint in zip(shoulder, elbow)]
    lower = [end - joint for joint, end in zip(elbow, wrist)]
    length = math.hypot(*upper) * math.hypot(*lower)
    if length < 1e-12:
        return None
    cosine = sum(a * b for a, b in zip(upper, lower)) / length
    return math.acos(max(-1.0, min(1.0, cosine)))


def extract_right_forearm_motion(clip: dict) -> list[tuple[int, float]]:
    """Return original timestamps and flexion in radians relative to the first reliable pose."""
    if clip.get("format") != "mediapipe-pose-landmarks" or clip.get("version") != 1:
        raise ValueError("Expected a version 1 MediaPipe pose clip.")

    timestamps = []
    observed = []
    for frame in clip["frames"]:
        timestamp = frame["time_ms"]
        if type(timestamp) is not int or timestamp < 0 or (timestamps and timestamp <= timestamps[-1]):
            raise ValueError("Frame times must be nonnegative, increasing integers.")
        timestamps.append(timestamp)
        flexion = elbow_flexion(frame["pose"])
        if flexion is not None:
            observed.append((timestamp, flexion))

    if len(observed) < 2 or len(observed) < MIN_COVERAGE * len(timestamps):
        raise ValueError("Keep the right shoulder, elbow and wrist visible throughout the clip.")

    first_time, baseline = observed[0]
    last_time, _ = observed[-1]
    if max(first_time - timestamps[0], timestamps[-1] - last_time) > MAX_GAP_MS:
        raise ValueError("The right arm is hidden for too long at the start or end of the clip.")

    motion = []
    left_index = 0
    for timestamp in timestamps:
        while left_index + 1 < len(observed) and observed[left_index + 1][0] <= timestamp:
            left_index += 1

        left_time, angle = observed[left_index]
        if left_time < timestamp < last_time:
            right_time, right_angle = observed[left_index + 1]
            if right_time - left_time > MAX_GAP_MS:
                raise ValueError("The right arm is hidden for too long within the clip.")
            fraction = (timestamp - left_time) / (right_time - left_time)
            angle += fraction * (right_angle - angle)
        motion.append((timestamp, angle - baseline))

    return motion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pose_clip", type=Path)
    args = parser.parse_args()
    try:
        clip = json.loads(args.pose_clip.read_text(encoding="utf-8"))
        motion = extract_right_forearm_motion(clip)
    except (AttributeError, IndexError, KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"Could not measure right forearm motion: {error}\n")
    print(json.dumps(motion, separators=(",", ":"), allow_nan=False))


if __name__ == "__main__":
    main()
