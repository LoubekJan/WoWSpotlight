"""Map canonical Spotlight rotations to the playable 12340 M2 bind skeletons."""

import math
import struct


RACE_MODELS = {
    1: "Human", 2: "Orc", 3: "Dwarf", 4: "NightElf", 5: "Scourge", 6: "Tauren",
    7: "Gnome", 8: "Troll", 10: "BloodElf", 11: "Draenei",
}
PLAYABLE_MODELS = tuple(race + sex for race in RACE_MODELS.values() for sex in ("Male", "Female"))
LOCAL_SLOT = 156

# Motion v1 indexes the HumanMale pelvis/spine, neck, shoulders, legs, arms and hands.
# Each row names those same roles in the target bind hierarchy, then its two toe pivots.
# The Tauren and Draenei ankle roles use the hocks, with the hooves as their endpoints.
CANONICAL_BONES = (1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18, 20, 22, 30, 31, 36, 38)
CANONICAL_PARENTS = (None, 1, 1, 2, 3, 3, 4, 4, 4, 7, 8, 9, 10, 11, 14, 15, 17, 18, 30, 31)
ROLE_BONES = {
    "HumanMale": (*CANONICAL_BONES, 32, 33),
    "HumanFemale": (1, 2, 3, 4, 5, 6, 11, 16, 17, 12, 13, 18, 19, 20, 21, 23, 33, 34, 39, 41, 35, 36),
    "OrcMale": (1, 2, 3, 4, 7, 8, 11, 12, 13, 16, 17, 18, 19, 20, 22, 24, 36, 37, 43, 45, 38, 39),
    "OrcFemale": (1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 15, 20, 21, 22, 23, 25, 35, 36, 42, 44, 37, 38),
    "DwarfMale": (1, 2, 3, 4, 7, 8, 11, 12, 13, 16, 17, 18, 19, 20, 22, 24, 37, 38, 44, 45, 39, 40),
    "DwarfFemale": (1, 2, 3, 4, 5, 6, 10, 15, 16, 11, 12, 17, 18, 19, 20, 22, 34, 35, 42, 44, 36, 37),
    "NightElfMale": (1, 2, 3, 4, 7, 8, 11, 12, 13, 16, 17, 18, 19, 20, 22, 24, 31, 32, 46, 48, 33, 34),
    "NightElfFemale": (1, 2, 3, 4, 7, 8, 11, 12, 13, 16, 17, 19, 20, 21, 23, 25, 39, 40, 45, 47, 41, 42),
    "ScourgeMale": (1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 15, 18, 19, 20, 21, 23, 36, 37, 41, 43, 38, 39),
    "ScourgeFemale": (1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 16, 20, 21, 22, 23, 24, 39, 41, 44, 45, 42, 43),
    "TaurenMale": (1, 2, 3, 4, 6, 5, 12, 19, 18, 14, 13, 20, 24, 23, 26, 25, 44, 43, 52, 51, 46, 45),
    "TaurenFemale": (1, 2, 3, 4, 5, 6, 13, 19, 20, 14, 15, 21, 24, 25, 26, 27, 42, 43, 49, 51, 44, 45),
    "GnomeMale": (1, 2, 3, 4, 5, 6, 9, 12, 13, 14, 15, 18, 19, 20, 21, 23, 34, 35, 39, 41, 36, 37),
    "GnomeFemale": (1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 18, 21, 22, 23, 25, 36, 37, 41, 43, 38, 39),
    "TrollMale": (1, 3, 2, 8, 6, 4, 17, 14, 13, 11, 9, 25, 24, 23, 22, 19, 29, 28, 43, 41, 27, 26),
    "TrollFemale": (1, 2, 3, 4, 7, 8, 9, 10, 11, 16, 17, 18, 19, 20, 23, 25, 34, 35, 38, 40, 36, 37),
    "BloodElfMale": (0, 1, 2, 3, 7, 4, 19, 20, 21, 15, 10, 28, 29, 30, 25, 23, 47, 48, 54, 55, 32, 31),
    "BloodElfFemale": (1, 2, 3, 10, 5, 6, 18, 19, 22, 11, 13, 27, 28, 29, 23, 24, 46, 48, 61, 63, 30, 31),
    "DraeneiMale": (1, 3, 2, 17, 5, 4, 24, 25, 23, 12, 11, 30, 31, 29, 19, 18, 44, 32, 51, 45, 27, 26),
    "DraeneiFemale": (1, 3, 2, 19, 7, 8, 24, 25, 28, 15, 16, 31, 32, 33, 21, 22, 44, 47, 49, 52, 29, 30),
}

BONE_SIZE = 88
LIMB_SEGMENTS = ((7, 14), (8, 15), (14, 20), (15, 22), (17, 30), (18, 31), (30, 36), (31, 38))


def model_path(model_name):
    if model_name not in ROLE_BONES:
        raise ValueError(f"Unsupported Spotlight model {model_name}.")
    sex = "Female" if model_name.endswith("Female") else "Male"
    race = model_name.removesuffix(sex)
    return fr"Character\{race}\{sex}\{model_name}.m2"


def skeleton(model):
    count, offset = struct.unpack_from("<2I", model, 44)
    if not count or offset + count * BONE_SIZE > len(model):
        raise ValueError("Invalid Spotlight skeleton table.")
    parents, pivots, key_bones = [], [], {}
    for bone in range(count):
        record = offset + bone * BONE_SIZE
        key, _, parent = struct.unpack_from("<iIh", model, record)
        if parent < -1 or parent >= count:
            raise ValueError("Invalid Spotlight skeleton parent.")
        parents.append(parent)
        pivots.append(struct.unpack_from("<3f", model, record + 76))
        if key >= 0:
            key_bones[key] = bone
    return parents, pivots, key_bones


def mapped_bones(parents, model_name):
    ids = ROLE_BONES.get(model_name)
    if ids is None:
        raise ValueError(f"Unsupported Spotlight model {model_name}.")
    if len(set(ids)) != len(ids) or any(not 0 <= bone < len(parents) for bone in ids):
        raise ValueError(f"Invalid Spotlight bone mapping for {model_name}.")
    target = dict(zip(CANONICAL_BONES, ids[:len(CANONICAL_BONES)], strict=True))
    mapped = set(target.values())
    for bone, parent in zip(CANONICAL_BONES, CANONICAL_PARENTS, strict=True):
        index = parents[target[bone]]
        visited = {target[bone]}
        while index != -1 and index not in mapped and index not in visited:
            visited.add(index)
            index = parents[index]
        if index != target.get(parent, -1) or index == target[bone]:
            raise ValueError(f"Unexpected {model_name} hierarchy at Spotlight bone {bone}.")
    if tuple(parents[bone] for bone in ids[-2:]) != (target[20], target[22]):
        raise ValueError(f"Unexpected {model_name} toe hierarchy.")
    return target


def bone_map(model, model_name):
    """Return canonical motion bone ID to the verified target bone ID."""
    return mapped_bones(skeleton(model)[0], model_name)


def difference(end, start):
    return tuple(last - first for last, first in zip(end, start, strict=True))


def hand_axis(pivots, keys, hand, fingers):
    knuckles = [pivots[keys[key]] for key in fingers if key in keys]
    if not knuckles:
        raise ValueError("The Spotlight rig has no hand landmarks.")
    center = tuple(sum(axis) / len(knuckles) for axis in zip(*knuckles, strict=True))
    return difference(center, pivots[hand])


def bind_directions(model_name, bones, pivots, keys):
    left_toe, right_toe = ROLE_BONES[model_name][-2:]
    axes = {bone: difference(pivots[bones[child]], pivots[bones[bone]]) for bone, child in LIMB_SEGMENTS}
    axes[20] = difference(pivots[left_toe], pivots[bones[20]])
    axes[22] = difference(pivots[right_toe], pivots[bones[22]])
    axes[36] = hand_axis(pivots, keys, bones[36], (13, 14, 15, 16))
    axes[38] = hand_axis(pivots, keys, bones[38], (8, 9, 10, 11))
    return axes


def unit(vector):
    length = math.hypot(*vector)
    if not math.isfinite(length) or length < 1e-8:
        raise ValueError("The Spotlight rig has a degenerate limb direction.")
    return tuple(value / length for value in vector)


def cross(first, second):
    x, y, z = first
    a, b, c = second
    return y * c - z * b, z * a - x * c, x * b - y * a


def swing(source, target):
    source, target = unit(source), unit(target)
    alignment = sum(a * b for a, b in zip(source, target, strict=True))
    if alignment <= -1 + 1e-8:
        smallest = min(range(3), key=lambda index: abs(source[index]))
        axis = tuple(float(index == smallest) for index in range(3))
        return (*unit(cross(source, axis)), 0.0)
    return unit((*cross(source, target), 1 + alignment))


def rotate_quaternion_basis(rotation, basis):
    # Conjugating by a unit quaternion rotates only the vector part of a joint rotation.
    vector, axis = rotation[:3], basis[:3]
    twice_cross = tuple(2 * value for value in cross(axis, vector))
    correction = cross(axis, twice_cross)
    return (*(value + basis[3] * crossed + delta
              for value, crossed, delta in zip(vector, twice_cross, correction, strict=True)), rotation[3])


def retarget_rotations(source_model, target_model, model_name, rotations):
    """Transport canonical joint rotations into each target limb's rest direction."""
    if model_name == "HumanMale":
        return rotations
    source_parents, source_pivots, source_keys = skeleton(source_model)
    parents, pivots, keys = skeleton(target_model)
    source_bones = mapped_bones(source_parents, "HumanMale")
    target_bones = mapped_bones(parents, model_name)
    source_axes = bind_directions("HumanMale", source_bones, source_pivots, source_keys)
    target_axes = bind_directions(model_name, target_bones, pivots, keys)
    converted = {}
    for bone, values in rotations.items():
        if bone in source_axes:
            basis = swing(source_axes[bone], target_axes[bone])
            values = [rotate_quaternion_basis(rotation, basis) for rotation in values]
        converted[target_bones[bone]] = values
    return converted
