"""Reduce model-space ankle drift during confidently inferred foot contact."""

import numpy as np
from scipy.spatial.transform import Rotation


# Bone 1 is the verified HumanMale M2 pelvis pivot. Bone 3 shares its rotation.
PELVIS_PIVOT = np.array([0.0, 0.0, 1.221828579902649])
LEGS = ((23, 25, 27, 29, 31, 7, 14, 20), (24, 26, 28, 30, 32, 8, 15, 22))
CONTACT_CONFIDENCE = 0.55
STILL_WINDOW_MS = 85
GROUND_WINDOW_MS = 350
MIN_CONTACT_MS = 170
FADE_MS = 90
MAX_SAMPLE_GAP_MS = 100
MAX_LOCAL_FOOT_SPREAD = 0.06
MAX_SPAN_FOOT_TRAVEL = 0.11
MAX_GROUND_DISTANCE = 0.14
MAX_OPPOSITE_FOOT_HEIGHT = 0.30
MAX_ANKLE_SHIFT = 0.06
MAX_LEG_CORRECTION = np.deg2rad(12)
EPSILON = 1e-7


def observed_foot(image, heel, toe):
    samples = image[:, [heel, toe]]
    points = samples[:, :, :2]
    valid = (np.isfinite(samples).all(axis=(1, 2)) & (samples[:, :, 3:] >= CONTACT_CONFIDENCE).all(axis=(1, 2))
             & ((points >= 0) & (points <= 1)).all(axis=(1, 2)))
    return points, valid


def contact_spans(times, image_points, heel, toe):
    """Infer likely support spans from a stationary, low, visible heel and toe."""
    if image_points is None:
        return []
    times = np.asarray(times)
    image = np.asarray(image_points)
    if image.shape != (len(times), 33, 5):
        return []

    torso_points = image[:, [11, 12, 23, 24]]
    confident_torso = (np.isfinite(torso_points).all(axis=(1, 2))
                        & (torso_points[:, :, 3:] >= CONTACT_CONFIDENCE).all(axis=(1, 2)))
    torso = torso_points[confident_torso, :, :2]
    if len(torso) < 3:
        return []
    scale = np.median(np.linalg.norm(torso[:, :2].mean(axis=1) - torso[:, 2:].mean(axis=1), axis=1))
    if scale < EPSILON:
        return []

    feet, valid = observed_foot(image, heel, toe)
    ground_y = feet[:, :, 1].mean(axis=1)
    opposite, opposite_valid = observed_foot(image, *((30, 32) if heel == 29 else (29, 31)))
    # A confidently visible lower foot helps reject a leg held still in the air.
    valid &= ~(opposite_valid & (opposite[:, :, 1].mean(axis=1) - ground_y > MAX_OPPOSITE_FOOT_HEIGHT * scale))
    still_start = np.searchsorted(times, times - STILL_WINDOW_MS)
    still_end = np.searchsorted(times, times + STILL_WINDOW_MS, side="right")
    floor_start = np.searchsorted(times, times - GROUND_WINDOW_MS)
    floor_end = np.searchsorted(times, times + GROUND_WINDOW_MS, side="right")

    support = []
    for index in np.flatnonzero(valid):
        local = slice(still_start[index], still_end[index])
        if local.stop - local.start < 3 or not valid[local].all():
            continue
        if np.linalg.norm(np.ptp(feet[local], axis=0), axis=1).max() > MAX_LOCAL_FOOT_SPREAD * scale:
            continue
        around = slice(floor_start[index], floor_end[index])
        if ground_y[around][valid[around]].max() - ground_y[index] <= MAX_GROUND_DISTANCE * scale:
            support.append(index)

    spans = []
    start = previous = None
    for index in support:
        if start is None:
            start = index
        elif (index != previous + 1 or times[index] - times[previous] > MAX_SAMPLE_GAP_MS
              or np.linalg.norm(feet[index] - feet[start], axis=1).max() > MAX_SPAN_FOOT_TRAVEL * scale):
            if times[previous] - times[start] >= MIN_CONTACT_MS:
                spans.append(slice(start, previous + 1))
            start = index
        previous = index
    if start is not None and times[previous] - times[start] >= MIN_CONTACT_MS:
        spans.append(slice(start, previous + 1))
    return spans


def solve_leg(hip, knee, ankle, target, upper_length, lower_length):
    """Solve a bounded ankle correction using the original knee bend plane."""
    original_upper, original_lower = knee - hip, ankle - knee
    original_axis = ankle - hip
    original_distance = np.linalg.norm(original_axis)
    if original_distance < EPSILON:
        return original_upper, original_lower
    original_axis /= original_distance
    bend = original_upper - original_axis * np.dot(original_upper, original_axis)
    # A nearly straight leg has an ambiguous knee pole. Apply less correction
    # there so noise does not choose a different bending direction each frame.
    bend_ratio = np.linalg.norm(bend) / (upper_length + lower_length)
    reliability = min(1.0, bend_ratio / 0.08)
    target = ankle + (target - ankle) * (reliability * reliability * (3 - 2 * reliability))
    direction = target - hip
    distance = np.linalg.norm(direction)
    if distance < EPSILON:
        return original_upper, original_lower
    direction /= distance
    bend -= direction * np.dot(bend, direction)
    bend_length = np.linalg.norm(bend)
    if bend_length < EPSILON:
        return original_upper, original_lower
    distance = np.clip(distance, abs(upper_length - lower_length) + EPSILON,
                       upper_length + lower_length - EPSILON)
    along = (upper_length ** 2 - lower_length ** 2 + distance ** 2) / (2 * distance)
    side = np.sqrt(max(0.0, upper_length ** 2 - along ** 2))
    upper = direction * along + bend * (side / bend_length)
    lower = direction * distance - upper
    angle = max(np.arccos(np.clip(np.dot(original_upper, upper) / upper_length**2, -1, 1)),
                np.arccos(np.clip(np.dot(original_lower, lower) / lower_length**2, -1, 1)))
    if angle > MAX_LEG_CORRECTION:
        weight = MAX_LEG_CORRECTION / angle
        upper = original_upper + weight * (upper - original_upper)
        lower = original_lower + weight * (lower - original_lower)
        upper *= upper_length / np.linalg.norm(upper)
        lower *= lower_length / np.linalg.norm(lower)
    return upper, lower


def stabilize_feet(times, model_points, image_points, available, pivots, pelvis):
    """Return thigh and shin aim directions, preserving the rig's fixed root."""
    times = np.asarray(times)
    if not isinstance(pelvis, Rotation):
        pelvis = Rotation.concatenate(pelvis)
    directions = {}
    for hip, knee, ankle, heel, toe, thigh, shin, foot in LEGS:
        upper = model_points[:, knee] - model_points[:, hip]
        lower = model_points[:, ankle] - model_points[:, knee]
        directions[thigh] = upper, lower
        spans = contact_spans(times, image_points, heel, toe) if toe in available else []
        if not spans:
            continue

        thigh_pivot, shin_pivot, foot_pivot = (np.asarray(pivots[bone]) for bone in (thigh, shin, foot))
        upper_length = np.linalg.norm(shin_pivot - thigh_pivot)
        lower_length = np.linalg.norm(foot_pivot - shin_pivot)
        upper_norm = np.linalg.norm(upper, axis=1)
        lower_norm = np.linalg.norm(lower, axis=1)
        valid = (upper_norm >= EPSILON) & (lower_norm >= EPSILON)
        hips = PELVIS_PIVOT + pelvis.apply(thigh_pivot - PELVIS_PIVOT)
        knees = hips + upper * (upper_length / np.maximum(upper_norm, EPSILON))[:, None]
        ankles = knees + lower * (lower_length / np.maximum(lower_norm, EPSILON))[:, None]
        max_shift = MAX_ANKLE_SHIFT * (upper_length + lower_length)
        for span in spans:
            if not valid[span].all():
                continue
            anchor = np.median(ankles[span], axis=0)
            start, end = times[span.start], times[span.stop - 1]
            for index in range(span.start + 1, span.stop - 1):
                weight = min(1.0, (times[index] - start) / FADE_MS, (end - times[index]) / FADE_MS)
                weight = weight * weight * (3.0 - 2.0 * weight)
                shift = anchor - ankles[index]
                distance = np.linalg.norm(shift)
                if distance < EPSILON:
                    continue
                target = ankles[index] + shift * (weight * min(1.0, max_shift / distance))
                upper[index], lower[index] = solve_leg(hips[index], knees[index], ankles[index], target,
                                                      upper_length, lower_length)
    return directions
