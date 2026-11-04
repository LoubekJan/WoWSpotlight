"""Capture one dancer's body landmarks from a ComfyUI VIDEO input."""

import math
import os
from pathlib import Path


MAX_DURATION_MS = 17_700
MAX_FRAMES = 1_800
MAX_BATCH_PIXELS = 400_000_000
MAX_FRAME_PIXELS = 36_000_000
LANDMARK_COUNT = 33
DEFAULT_MODEL = Path(__file__).parent / "models" / "pose_landmarker_full.task"


def serialize_landmarks(landmarks):
    return [
        [point.x, point.y, point.z, point.visibility, point.presence]
        for point in landmarks
    ]


def bounded_dimensions(width, height):
    if min(width, height) <= 0 or width * height > MAX_FRAME_PIXELS:
        raise ValueError("The video frame dimensions are unsupported. Reduce its resolution.")
    max_width, max_height = (1280, 720) if width >= height else (720, 1280)
    scale = min(1.0, max_width / width, max_height / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def stream_frames(video):
    import av
    import numpy as np

    start, duration = video.get_active_trim_window()
    with av.open(video.get_stream_source(), mode="r") as container:
        stream = next(iter(container.streams.video), None)
        if stream is None:
            raise ValueError("The file does not contain a video stream.")
        bounded_dimensions(stream.width, stream.height)
        origin = stream.start_time * stream.time_base if stream.start_time is not None else None
        if start and origin is not None:
            container.seek(int((origin + start) / stream.time_base), stream=stream)

        first_time = None
        for frame in container.decode(stream):
            if frame.pts is None or frame.time_base is None:
                raise ValueError("The video contains a frame without a presentation timestamp.")
            presentation_time = frame.pts * frame.time_base
            if origin is None:
                origin = presentation_time
            elapsed = float(presentation_time - origin)
            if elapsed < start:
                continue
            if duration and elapsed >= start + duration:
                break
            if first_time is None:
                first_time = presentation_time
            time_ms = (presentation_time - first_time) * 1_000
            if time_ms > MAX_DURATION_MS:
                break

            width, height = bounded_dimensions(frame.width, frame.height)
            rgb = frame.reformat(width=width, height=height, format="rgb24").to_ndarray()
            rotation = int(round(getattr(frame, "rotation", 0) / 90))
            if rotation % 4:
                rgb = np.rot90(rgb, k=rotation)
            yield round(time_ms), np.ascontiguousarray(rgb)


def component_frames(video):
    import numpy as np
    from PIL import Image

    width, height = video.get_dimensions()
    target_size = bounded_dimensions(width, height)
    frame_count = video.get_frame_count()
    if frame_count < 2:
        raise ValueError("Use a video with at least two decodable frames.")

    components = video.get_components()
    fps = float(components.frame_rate)
    if not math.isfinite(fps) or not 0 < fps <= 1_000:
        raise ValueError("The video does not have a valid frame rate.")
    clip_frame_count = min(frame_count, math.floor(MAX_DURATION_MS * fps / 1_000) + 1)
    if width * height * clip_frame_count > MAX_BATCH_PIXELS:
        raise ValueError("The selected video frames are too large. Reduce their resolution.")
    for index, frame in enumerate(components.images):
        time_ms = index * 1_000 / fps
        if time_ms > MAX_DURATION_MS:
            break
        rgb = np.clip(frame.detach().cpu().numpy(), 0.0, 1.0)
        rgb = np.ascontiguousarray((rgb * 255).astype(np.uint8))
        if target_size != (width, height):
            rgb = np.asarray(Image.fromarray(rgb).resize(target_size, Image.Resampling.BILINEAR))
        yield round(time_ms), rgb


class SpotlightCapturePose:
    CATEGORY = "Spotlight"
    FUNCTION = "capture"
    RETURN_TYPES = ("SPOTLIGHT_POSE",)
    RETURN_NAMES = ("pose",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("VIDEO",)}}

    def capture(self, video):
        model_path = Path(os.environ.get("SPOTLIGHT_POSE_MODEL") or DEFAULT_MODEL)
        if not model_path.is_file():
            raise ValueError(f"Install the MediaPipe Pose Landmarker Full model at {model_path}.")

        import mediapipe as mp

        options = mp.tasks.vision.PoseLandmarkerOptions(
            # The server's pooled storage supports reads but cannot map this model file.
            base_options=mp.tasks.BaseOptions(model_asset_buffer=model_path.read_bytes()),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=1,
        )
        frames = []
        detected = 0
        # VideoFromComponents has a default stream source that re-encodes the entire batch.
        # Only VideoFromFile exposes the native source together with its trim window.
        read_frames = stream_frames if hasattr(video, "get_active_trim_window") else component_frames
        with mp.tasks.vision.PoseLandmarker.create_from_options(options) as landmarker:
            for time_ms, rgb in read_frames(video):
                if frames and time_ms <= frames[-1]["time_ms"]:
                    raise ValueError("Video timestamps must increase on every frame.")
                if len(frames) >= MAX_FRAMES:
                    raise ValueError("Use a lower frame rate. The selected clip exceeds 1,800 frames.")
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect_for_video(image, time_ms)
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

        if len(frames) < 2:
            raise ValueError("Use a video with at least two decodable frames.")
        if detected == 0:
            raise ValueError("No person was detected. Use a well-lit video with the full body in view.")
        return ({
            "format": "mediapipe-pose-landmarks",
            "version": 1,
            "detected_frames": detected,
            "frames": frames,
        },)
