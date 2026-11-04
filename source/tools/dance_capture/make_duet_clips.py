"""Generate two visibly distinct HumanMale clips for the duet test."""

import argparse
import json
from math import cos, radians, sin, tau
from pathlib import Path

if __package__:
    from .client_poc import FULL_BODY_BONES, FULL_BODY_FORMAT, RIGHT_ARM
    from .spotlight_comfy import SLOT_DURATION_MS
else:
    from client_poc import FULL_BODY_BONES, FULL_BODY_FORMAT, RIGHT_ARM
    from spotlight_comfy import SLOT_DURATION_MS


LEFT_ARM = 17
FRAME_COUNT = 101
FRAMES_PER_WAVE = 10
IDENTITY = (0, 0, 0, 1)


def wave_clip(arm, direction):
    frames = []
    for index in range(FRAME_COUNT):
        time_ms = round(index * SLOT_DURATION_MS / (FRAME_COUNT - 1))
        half_angle = radians(direction * (110 + 30 * sin(tau * index / FRAMES_PER_WAVE))) / 2
        rotations = dict.fromkeys(map(str, FULL_BODY_BONES), IDENTITY)
        # Positive X rotation raises the left upper arm. The right arm is mirrored.
        rotations[str(arm)] = (sin(half_angle), 0, 0, cos(half_angle))
        frames.append({"time_ms": time_ms, "rotations": rotations})
    return {"format": FULL_BODY_FORMAT, "version": 1, "model": "HumanMale", "frames": frames}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for side, arm, direction in (("left", LEFT_ARM, 1), ("right", RIGHT_ARM, -1)):
        output = args.output_dir / f"{side}-arm.motion.json"
        output.write_text(json.dumps(wave_clip(arm, direction), separators=(",", ":")) + "\n", encoding="utf-8")
        print(output)


if __name__ == "__main__":
    main()
