"""Retarget one MediaPipe capture onto the verified WoW 3.3.5a HumanMale rig."""

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.spatial.transform import Rotation

from .feet import stabilize_feet


# Bind pivots from HumanMale.m2 in Client-Lab patch-3.MPQ (build 12340).
# M2 rotations are parent-relative, but each bind pivot is in model coordinates.
PIVOTS = {
    7: (0.0297, 0.1319, 1.0771), 8: (0.0297, -0.1319, 1.0771),
    14: (-0.0110, 0.1694, 0.5802), 15: (-0.0110, -0.1694, 0.5803),
    17: (-0.0624, 0.2576, 1.6315), 18: (-0.0624, -0.2576, 1.6315),
    20: (-0.0926, 0.2037, 0.1049), 22: (-0.0926, -0.2037, 0.1050),
    30: (-0.1251, 0.3715, 1.2891), 31: (-0.1251, -0.3715, 1.2891),
    32: (0.1253, 0.2091, 0.0174), 33: (0.1251, -0.2009, 0.0169),
    36: (-0.0713, 0.4644, 1.0096), 38: (-0.0713, -0.4644, 1.0096),
    40: (-0.0869, 0.5403, 0.8986), 42: (-0.0062, 0.5330, 0.9042),
    45: (-0.0082, -0.5341, 0.9095), 48: (-0.0869, -0.5403, 0.8986),
}
CORE_LANDMARKS = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
OPTIONAL_LANDMARKS = (0, 7, 8, 17, 18, 19, 20, 31, 32)
ARM_SHOULDERS = {13: 11, 14: 12, 15: 11, 16: 12}
MIN_CONFIDENCE = 0.35
MIN_COVERAGE = 0.75
MAX_EDGE_GAP_MS = 300
MAX_POSE_GAP_MS = 350
MAX_LANDMARK_GAP_MS = 450
MAX_ARM_OCCLUSION_MS = 800
MIN_ARM_COVERAGE = 0.85
MIN_OCCLUDED_VISIBILITY = 0.20
MIN_OCCLUDED_PRESENCE = 0.65
MIN_EDGE_RUN_MS = 200
MIN_TRIMMED_DURATION_MS = 1_000
MIN_RETAINED_FRACTION = 0.5
SMOOTH_SIGMA_MS = 38
SMOOTH_WINDOW_MS = 100
SLOT_DURATION_MS = 17_700
UP = np.array([0.0, 0.0, 1.0])


def short_gaps(times, observed, interior_limit):
    return (len(observed) >= max(2, MIN_COVERAGE * len(times))
            and observed[0] - times[0] <= MAX_EDGE_GAP_MS
            and times[-1] - observed[-1] <= MAX_EDGE_GAP_MS
            and np.diff(observed).max() <= interior_limit)


def trim_untracked_edges(times, detected):
    """Find sustained edge detections without cutting around a tracking gap in the dance."""
    indices = np.flatnonzero(detected)
    splits = np.flatnonzero(np.diff(times[indices]) > MAX_POSE_GAP_MS) + 1
    runs = [run for run in np.split(indices, splits)
            if len(run) >= 2 and times[run[-1]] - times[run[0]] >= MIN_EDGE_RUN_MS
            and len(run) >= MIN_COVERAGE * (run[-1] - run[0] + 1)]
    if not runs:
        return slice(None)
    first, last = runs[0][0], runs[-1][-1]
    if times[first] - times[0] <= MAX_EDGE_GAP_MS:
        first = 0
    if times[-1] - times[last] <= MAX_EDGE_GAP_MS:
        last = len(times) - 1
    minimum = max(MIN_TRIMMED_DURATION_MS, MIN_RETAINED_FRACTION * (times[-1] - times[0]))
    if times[last] - times[first] < minimum:
        return slice(None)
    return slice(first, last + 1)


def recover_arm_observations(times, raw, image, index, valid):
    """Use in-frame estimates to bridge short occlusions of an otherwise tracked arm."""
    observed = times[valid]
    if len(observed) < MIN_ARM_COVERAGE * len(times) or not short_gaps(times, observed, MAX_ARM_OCCLUSION_MS):
        return valid
    samples = raw[:, index]
    shoulder = raw[:, ARM_SHOULDERS[index]]
    xy = image[:, index, :2]
    candidates = (np.isfinite(samples).all(axis=1) & np.isfinite(shoulder).all(axis=1)
                  & (samples[:, 3] >= MIN_OCCLUDED_VISIBILITY) & (samples[:, 4] >= MIN_OCCLUDED_PRESENCE)
                  & (shoulder[:, 3:] >= MIN_CONFIDENCE).all(axis=1) & ((xy >= 0) & (xy <= 1)).all(axis=1))
    recovered = valid.copy()
    for first, last in zip(observed, observed[1:]):
        if last - first > MAX_LANDMARK_GAP_MS:
            recovered |= candidates & (times > first) & (times < last)
    return recovered


def smooth_observations(times, points, confidence):
    """Fit the position at each timestamp from a centered local linear fit."""
    result = points.copy()
    starts = np.searchsorted(times, times - SMOOTH_WINDOW_MS)
    ends = np.searchsorted(times, times + SMOOTH_WINDOW_MS, side="right")
    for index, (start, end) in enumerate(zip(starts, ends)):
        if end - start < 3:
            continue
        offsets = (times[start:end] - times[index]) / SMOOTH_SIGMA_MS
        weights = np.exp(-0.5 * offsets**2) * confidence[start:end]**2
        total = weights.sum()
        first = np.dot(weights, offsets)
        second = np.dot(weights, offsets**2)
        denominator = total * second - first**2
        if denominator > 1e-8:
            coefficients = weights * (second - first * offsets) / denominator
            result[index] = coefficients @ points[start:end]
    return result


def recover_points(clip):
    if clip.get("format") != "mediapipe-pose-landmarks" or clip.get("version") != 1:
        raise ValueError("Expected a version 1 MediaPipe pose clip.")
    frames = clip["frames"]
    if not 2 <= len(frames) <= 1_800:
        raise ValueError("Retargeting requires 2 to 1,800 frames.")
    times = [frame["time_ms"] for frame in frames]
    if times[0] != 0 or any(type(time) is not int for time in times) or any(
        first >= second for first, second in zip(times, times[1:])
    ):
        raise ValueError("Frame times must increase in milliseconds, starting at zero.")
    if times[-1] > SLOT_DURATION_MS:
        raise ValueError("The clip exceeds the 17.7-second HumanMale animation slot.")

    times = np.asarray(times)
    raw = np.full((len(frames), 33, 5), np.nan)
    image = np.full_like(raw, np.nan)
    detected = np.zeros(len(frames), dtype=bool)
    for index, frame in enumerate(frames):
        if frame["pose"] is not None:
            points = np.asarray(frame["pose"]["world"], dtype=float)
            if points.shape != (33, 5):
                raise ValueError("Each pose needs 33 world points with confidence values.")
            raw[index] = points
            detected[index] = True
            pixels = np.asarray(frame["pose"].get("image"), dtype=float)
            if pixels.shape == (33, 5):
                image[index] = pixels

    if not short_gaps(times, times[detected], MAX_POSE_GAP_MS):
        window = trim_untracked_edges(times, detected)
        times, detected = times[window], detected[window]
        raw, image = raw[window], image[window]
        times = times - times[0]
        if not short_gaps(times, times[detected], MAX_POSE_GAP_MS):
            raise ValueError("Whole-body tracking was lost for too long. Keep the dancer in view.")

    # MediaPipe's front-facing, image-aligned axes become WoW forward, left, up.
    model_points = raw[:, :, [2, 0, 1]] * [-1, 1, -1]
    available = set()
    for index in CORE_LANDMARKS + OPTIONAL_LANDMARKS:
        samples = raw[:, index]
        valid = np.isfinite(samples).all(axis=1) & (samples[:, 3:] >= MIN_CONFIDENCE).all(axis=1)
        if index in ARM_SHOULDERS and not short_gaps(times, times[valid], MAX_LANDMARK_GAP_MS):
            valid = recover_arm_observations(times, raw, image, index, valid)
        observed = times[valid]
        if not short_gaps(times, observed, MAX_LANDMARK_GAP_MS):
            if index in CORE_LANDMARKS:
                raise ValueError(f"Landmark {index} is obscured for too long. Keep the full body in view.")
            continue
        confidence = np.clip(samples[valid, 3:].min(axis=1), 0.0, 1.0)
        filtered = smooth_observations(observed, model_points[valid, index], confidence)
        trajectory = PchipInterpolator(observed, filtered, axis=0)
        model_points[:, index] = trajectory(np.clip(times, observed[0], observed[-1]))
        available.add(index)
    return times.tolist(), model_points, available, image


def unit(vector):
    length = np.linalg.norm(vector)
    if length < 1e-7:
        raise ValueError("A pose contains a zero-length joint direction.")
    return vector / length


def body_frame(left, up):
    left = unit(left)
    forward = unit(np.cross(left, up))
    return Rotation.from_matrix(np.column_stack((forward, left, np.cross(forward, left))))


def shortest_swing(start, end):
    start, end = unit(start), unit(end)
    dot = np.clip(np.dot(start, end), -1.0, 1.0)
    axis = np.cross(start, end)
    if dot < -1 + 1e-8:
        # Any perpendicular axis gives the 180-degree swing. Pick it consistently.
        basis = np.eye(3)[np.argmin(np.abs(start))]
        return Rotation.from_rotvec(np.pi * unit(np.cross(start, basis)))
    return Rotation.from_quat([*axis, 1 + dot])


def midpoint(first, second):
    return (first + second) * 0.5


def retarget_pose(clip):
    times, model_points, available, image = recover_points(clip)
    pivots = {bone: np.asarray(point) for bone, point in PIVOTS.items()}
    rest_left_hip, rest_right_hip = pivots[7], pivots[8]
    rest_left_shoulder, rest_right_shoulder = pivots[17], pivots[18]
    rest_torso = midpoint(rest_left_shoulder, rest_right_shoulder) - midpoint(rest_left_hip, rest_right_hip)
    rest_pelvis_inverse = body_frame(rest_left_hip - rest_right_hip, UP).inv()
    rest_chest = body_frame(rest_left_shoulder - rest_right_shoulder, rest_torso)
    pelvis_frames = [body_frame(points[23] - points[24], UP) * rest_pelvis_inverse for points in model_points]
    leg_directions = stabilize_feet(times, model_points, image, available, pivots, pelvis_frames)
    identity = Rotation.identity()
    frames = []
    previous = {}

    for frame, (time, points, pelvis) in enumerate(zip(times, model_points, pelvis_frames)):
        local = {}
        world = {0: identity}

        def place(bone, parent, orientation):
            world[bone] = orientation
            local[bone] = world[parent].inv() * orientation

        def aim(bone, parent, rest_direction, target_direction):
            inherited = world[parent]
            swing = shortest_swing(inherited.apply(rest_direction), target_direction)
            place(bone, parent, swing * inherited)

        left_hip, right_hip = points[23], points[24]
        left_shoulder, right_shoulder = points[11], points[12]
        torso = midpoint(left_shoulder, right_shoulder) - midpoint(left_hip, right_hip)
        chest = body_frame(left_shoulder - right_shoulder, torso) * rest_chest.inv()
        place(1, 0, pelvis)
        place(2, 1, chest)
        place(3, 1, pelvis)
        place(4, 2, chest)
        place(9, 4, chest)
        place(10, 4, chest)
        place(11, 4, chest)

        # Upper limbs. A shortest swing preserves inherited axial twist where the capture
        # supplies a bone direction but not an unambiguous twist around that direction.
        for shoulder, elbow, wrist, pinky, index, clavicle, upper, lower, hand, knuckles in (
            (11, 13, 15, 17, 19, 10, 17, 30, 36, (40, 42)),
            (12, 14, 16, 18, 20, 11, 18, 31, 38, (45, 48)),
        ):
            aim(upper, clavicle, pivots[lower] - pivots[upper], points[elbow] - points[shoulder])
            aim(lower, upper, pivots[hand] - pivots[lower], points[wrist] - points[elbow])
            if {pinky, index} <= available:
                rest_hand = midpoint(pivots[knuckles[0]], pivots[knuckles[1]]) - pivots[hand]
                aim(hand, lower, rest_hand, midpoint(points[pinky], points[index]) - points[wrist])
            else:
                place(hand, lower, world[lower])

        # Lower limbs and foot pitch. This stage reproduces joint directions in place.
        for ankle, toe, thigh, shin, foot, toe_pivot in (
            (27, 31, 7, 14, 20, 32),
            (28, 32, 8, 15, 22, 33),
        ):
            upper, lower = leg_directions[thigh]
            aim(thigh, 3, pivots[shin] - pivots[thigh], upper[frame])
            aim(shin, thigh, pivots[foot] - pivots[shin], lower[frame])
            if toe in available:
                aim(foot, shin, pivots[toe_pivot] - pivots[foot], points[toe] - points[ankle])
            else:
                place(foot, shin, world[shin])

        if {0, 7, 8} <= available:
            # Facial forward is estimated from the line from the ears to the nose.
            left = unit(points[7] - points[8])
            forward = points[0] - midpoint(points[7], points[8])
            place(16, 9, body_frame(left, np.cross(forward, left)))
        else:
            place(16, 9, chest)

        rotations = {}
        for bone, rotation in local.items():
            quaternion = rotation.as_quat()
            if bone in previous and np.dot(previous[bone], quaternion) < 0:
                quaternion = -quaternion
            previous[bone] = quaternion
            rotations[str(bone)] = quaternion.tolist()
        frames.append({"time_ms": time, "rotations": rotations})

    return {"format": "wow-spotlight-motion", "version": 1, "model": "HumanMale",
            "loop": times[-1] >= 500 and len(frames) >= 5, "frames": frames}


class SpotlightRetargetHumanMale:
    CATEGORY = "Spotlight/WoW"
    RETURN_TYPES = ("SPOTLIGHT_MOTION",)
    RETURN_NAMES = ("motion",)
    FUNCTION = "retarget"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"pose": ("SPOTLIGHT_POSE",)}}

    def retarget(self, pose):
        return (retarget_pose(pose),)
