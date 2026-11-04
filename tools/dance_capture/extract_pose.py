"""Extract a single dancer's body landmarks from a local video."""

import argparse
import json
import math
from pathlib import Path
import tempfile


MAX_DURATION_MS = 30_000
MAX_FRAMES = 1_800
LANDMARK_COUNT = 33


def serialize_landmarks(landmarks):
    return [
        [point.x, point.y, point.z, point.visibility, point.presence]
        for point in landmarks
    ]


def extract_pose(video_path, model_path):
    import cv2
    import mediapipe as mp

    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1,
    )
    capture = cv2.VideoCapture(str(video_path))
    frames = []
    detected = 0
    previous_time_ms = -1
    start_time_ms = None
    try:
        if not capture.isOpened():
            raise ValueError("The video could not be opened.")

        with mp.tasks.vision.PoseLandmarker.create_from_options(options) as landmarker:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break

                source_time_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
                if not math.isfinite(source_time_ms) or source_time_ms < 0:
                    raise ValueError("The video decoder did not provide valid timestamps.")
                if start_time_ms is None:
                    start_time_ms = source_time_ms
                time_ms = round(source_time_ms - start_time_ms)
                if time_ms <= previous_time_ms:
                    raise ValueError("Video timestamps must increase on every frame.")
                if time_ms >= MAX_DURATION_MS or len(frames) >= MAX_FRAMES:
                    raise ValueError("Use a video up to 30 seconds and 1,800 frames.")
                previous_time_ms = time_ms

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), time_ms)
                pose = None
                if result.pose_landmarks and result.pose_world_landmarks:
                    image_points = result.pose_landmarks[0]
                    world_points = result.pose_world_landmarks[0]
                    if len(image_points) != LANDMARK_COUNT or len(world_points) != LANDMARK_COUNT:
                        raise ValueError("The model returned an unexpected number of body landmarks.")
                    pose = {
                        "image": serialize_landmarks(image_points),
                        "world": serialize_landmarks(world_points),
                    }
                    detected += 1
                frames.append({"time_ms": time_ms, "pose": pose})
    finally:
        capture.release()

    if len(frames) < 2:
        raise ValueError("Use a video with at least two decodable frames.")
    if detected == 0:
        raise ValueError("No person was detected. Use a well-lit clip with the full body in view.")
    return {
        "format": "mediapipe-pose-landmarks",
        "version": 1,
        "detected_frames": detected,
        "frames": frames,
    }


def write_clip(output_path, clip):
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_path.parent, delete=False) as stream:
            temporary_path = Path(stream.name)
            json.dump(clip, stream, separators=(",", ":"), allow_nan=False)
            stream.write("\n")
        temporary_path.replace(output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", type=Path, required=True, help="Path to a Pose Landmarker .task file")
    args = parser.parse_args()

    for path in (args.video, args.model):
        if not path.is_file():
            parser.error(f"File not found: {path}")
    if args.output.suffix.lower() != ".json":
        parser.error("Use a .json output path.")
    if args.output.resolve() in {args.video.resolve(), args.model.resolve()}:
        parser.error("The output must be separate from the video and model.")

    try:
        clip = extract_pose(args.video, args.model)
        write_clip(args.output, clip)
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"Dance capture failed: {error}\n")
    print(f"Detected pose in {clip['detected_frames']}/{len(clip['frames'])} frames. Saved {args.output}")


if __name__ == "__main__":
    main()
