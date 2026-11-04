"""Retarget one MediaPipe capture onto the verified WoW 3.3.5a HumanMale rig."""

import numpy as np
from scipy.spatial.transform import Rotation


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
MIN_CONFIDENCE = 0.35
MIN_COVERAGE = 0.75
MAX_GAP_MS = 300
SLOT_DURATION_MS = 17_700
UP = np.array([0.0, 0.0, 1.0])


def recover_points(clip):
    if clip.get("format") != "mediapipe-pose-landmarks" or clip.get("version") != 1:
        raise ValueError("Expected a version 1 MediaPipe pose clip.")
    frames = clip["frames"]
    if len(frames) < 2:
        raise ValueError("At least two frames are required for retargeting.")
    times = [frame["time_ms"] for frame in frames]
    if times[0] != 0 or any(type(time) is not int for time in times) or any(
        first >= second for first, second in zip(times, times[1:])
    ):
        raise ValueError("Frame times must increase in milliseconds, starting at zero.")
    if times[-1] > SLOT_DURATION_MS:
        raise ValueError("The clip exceeds the 17.7-second HumanMale animation slot.")

    raw = np.full((len(frames), 33, 5), np.nan)
    for index, frame in enumerate(frames):
        if frame["pose"] is not None:
            points = np.asarray(frame["pose"]["world"], dtype=float)
            if points.shape != (33, 5):
                raise ValueError("Each pose needs 33 world points with confidence values.")
            raw[index] = points

    # MediaPipe's front-facing, image-aligned axes become WoW forward, left, up.
    model_points = raw[:, :, [2, 0, 1]] * [-1, 1, -1]
    available = set()
    for index in CORE_LANDMARKS + OPTIONAL_LANDMARKS:
        samples = raw[:, index]
        valid = np.isfinite(samples).all(axis=1) & (samples[:, 3:] >= MIN_CONFIDENCE).all(axis=1)
        observed = np.asarray(times)[valid]
        has_coverage = len(observed) >= max(2, MIN_COVERAGE * len(times))
        has_short_gaps = has_coverage and np.diff([times[0], *observed, times[-1]]).max() <= MAX_GAP_MS
        if not has_short_gaps:
            if index in CORE_LANDMARKS:
                raise ValueError(f"Landmark {index} is obscured for too long. Keep the full body in view.")
            continue
        for axis in range(3):
            model_points[:, index, axis] = np.interp(times, observed, model_points[valid, index, axis])
        available.add(index)
    return times, model_points, available


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
    times, model_points, available = recover_points(clip)
    pivots = {bone: np.asarray(point) for bone, point in PIVOTS.items()}
    rest_left_hip, rest_right_hip = pivots[7], pivots[8]
    rest_left_shoulder, rest_right_shoulder = pivots[17], pivots[18]
    rest_torso = midpoint(rest_left_shoulder, rest_right_shoulder) - midpoint(rest_left_hip, rest_right_hip)
    rest_pelvis = body_frame(rest_left_hip - rest_right_hip, UP)
    rest_chest = body_frame(rest_left_shoulder - rest_right_shoulder, rest_torso)
    identity = Rotation.identity()
    frames = []
    previous = {}

    for time, points in zip(times, model_points):
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
        pelvis = body_frame(left_hip - right_hip, UP) * rest_pelvis.inv()
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
        for hip, knee, ankle, toe, thigh, shin, foot, toe_pivot in (
            (23, 25, 27, 31, 7, 14, 20, 32),
            (24, 26, 28, 32, 8, 15, 22, 33),
        ):
            aim(thigh, 3, pivots[shin] - pivots[thigh], points[knee] - points[hip])
            aim(shin, thigh, pivots[foot] - pivots[shin], points[ankle] - points[knee])
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

    return {"format": "wow-spotlight-motion", "version": 1, "model": "HumanMale", "frames": frames}


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
