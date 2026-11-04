"""Convert an MP4 with the lab's Spotlight ComfyUI workflow."""

import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

if __package__:
    from .client_poc import FULL_BODY_FORMAT, full_body_motion
else:
    from client_poc import FULL_BODY_FORMAT, full_body_motion


DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
SLOT_DURATION_MS = 17_700
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
POLL_SECONDS = 1


class ComfyError(RuntimeError):
    """The remote Spotlight workflow could not produce a usable motion clip."""


def remaining_time(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Vypršel čas na převod videa v ComfyUI.")
    return remaining


def request_bytes(base_url, endpoint, deadline, *, data=None, headers=None):
    request = Request(base_url + "/api" + endpoint, data=data, headers=headers or {})
    with urlopen(request, timeout=min(30, remaining_time(deadline))) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    remaining_time(deadline)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ComfyError("Odpověď ComfyUI překročila povolenou velikost.")
    return body


def json_object(body):
    try:
        value = json.loads(body)
    except ValueError as error:
        raise ComfyError("ComfyUI vrátilo neplatná data JSON.") from error
    if not isinstance(value, dict):
        raise ComfyError("ComfyUI vrátilo neočekávaná data.")
    return value


def multipart_video(stream, size, prefix, suffix, deadline):
    yield prefix
    while size:
        remaining_time(deadline)
        chunk = stream.read(min(size, UPLOAD_CHUNK_BYTES))
        if not chunk:
            raise OSError("Video se během nahrávání změnilo.")
        yield chunk
        size -= len(chunk)
    yield suffix


def upload_video(base_url, video_path, deadline):
    upload_name = f"spotlight-companion-{uuid4().hex}.mp4"
    boundary = f"Spotlight{uuid4().hex}"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{upload_name}"\r\n'
        "Content-Type: video/mp4\r\n\r\n"
    ).encode("ascii")
    suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
    with video_path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        if size == 0:
            raise ValueError("Vybrané MP4 je prázdné.")
        response = request_bytes(
            base_url, "/upload/image", deadline,
            data=multipart_video(stream, size, prefix, suffix, deadline),
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(prefix) + size + len(suffix)),
            },
        )
    uploaded = json_object(response)
    if uploaded.get("name") != upload_name or uploaded.get("subfolder") or uploaded.get("type") != "input":
        raise ComfyError("ComfyUI nepotvrdilo uložení vstupního MP4.")
    return upload_name


def queue_workflow(base_url, upload_name, deadline):
    # API form of the four-node Spotlight - Video to WoW Motion workflow.
    graph = {
        "1": {"class_type": "LoadVideo", "inputs": {"file": upload_name}},
        "2": {"class_type": "SpotlightCapturePose", "inputs": {"video": ["1", 0]}},
        "3": {"class_type": "SpotlightRetargetHumanMale", "inputs": {"pose": ["2", 0]}},
        "4": {"class_type": "SpotlightSaveMotion", "inputs": {"motion": ["3", 0], "name": "spotlight-companion"}},
    }
    response = json_object(request_bytes(
        base_url, "/prompt", deadline, data=json.dumps({"prompt": graph}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    ))
    prompt_id = response.get("prompt_id")
    if not isinstance(prompt_id, str) or not prompt_id:
        raise ComfyError("ComfyUI nepotvrdilo zařazení převodu.")
    return prompt_id


def history_result(base_url, prompt_id, deadline):
    endpoint = "/history/" + quote(prompt_id, safe="")
    while True:
        try:
            entry = json_object(request_bytes(base_url, endpoint, deadline)).get(prompt_id)
        except HTTPError as error:
            if error.code not in (429, 502, 503, 504):
                raise
            error.close()
        except (URLError, TimeoutError):
            pass  # History reads are safe to retry.
        else:
            if entry is not None:
                return entry
        time.sleep(min(POLL_SECONDS, remaining_time(deadline)))


def output_file(entry):
    try:
        status = entry["status"]
        if status["status_str"] != "success" or status["completed"] is not True:
            for event, data in reversed(status.get("messages", [])):
                if event == "execution_error" and data.get("exception_message"):
                    raise ComfyError(str(data["exception_message"]).strip())
                if event == "execution_interrupted":
                    raise ComfyError("Převod v ComfyUI byl přerušen.")
            raise ComfyError("Převod v ComfyUI se nezdařil.")
        output = entry["outputs"]["4"]["spotlight_files"][0]
        filename = output["filename"]
        if (output["type"] != "output" or output["subfolder"] != "spotlight"
                or not filename.endswith(".motion.json") or "/" in filename or "\\" in filename):
            raise ValueError("Invalid motion file reference")
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
        raise ComfyError("ComfyUI nevrátilo výstupní soubor animace Spotlight.") from error
    return output


def publish_motion(body, active_path):
    motion = json_object(body)
    try:
        if motion.get("format") != FULL_BODY_FORMAT:
            raise ValueError("Expected Spotlight motion format")
        times, _ = full_body_motion(motion, SLOT_DURATION_MS)
        payload = json.dumps(motion, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as error:
        raise ComfyError(f"Stažená animace není platná: {error}") from error

    active_path.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with NamedTemporaryFile(dir=active_path.parent, delete=False) as stream:
            staged = Path(stream.name)
            stream.write(payload)
        staged.replace(active_path)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return len(times), times[-1]


def run_comfy_video(video_path, active_path, *, base_url=DEFAULT_COMFY_URL, on_status=None, timeout=600):
    """Run the conversion and publish the validated clip for the local watcher."""
    video_path = Path(video_path)
    active_path = Path(active_path)
    if video_path.suffix.lower() != ".mp4" or not video_path.is_file():
        raise ValueError("Vyber existující video ve formátu MP4.")
    if active_path.suffix.lower() != ".json" or active_path.resolve() == video_path.resolve():
        raise ValueError("Vyber samostatný soubor JSON pro aktivní animaci.")
    base_url = base_url.rstrip("/")
    url = urlsplit(base_url)
    if url.scheme not in ("http", "https") or not url.hostname or url.query or url.fragment:
        raise ValueError("Zadej platnou adresu ComfyUI.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Časový limit převodu musí být kladný.")

    report = on_status if on_status is not None else lambda _: None
    deadline = time.monotonic() + timeout
    try:
        report("Nahrávám video do ComfyUI…")
        upload_name = upload_video(base_url, video_path, deadline)
        report("Zařazuji převod do fronty…")
        prompt_id = queue_workflow(base_url, upload_name, deadline)
        report("Čekám na zpracování pohybu…")
        output = output_file(history_result(base_url, prompt_id, deadline))
        report("Stahuji a ověřuji animaci…")
        query = urlencode({key: output[key] for key in ("filename", "subfolder", "type")})
        motion = request_bytes(base_url, "/view?" + query, deadline)
        frames, duration = publish_motion(motion, active_path)
    except HTTPError as error:
        with error:
            detail = error.read(4096).decode("utf-8", errors="replace").strip()
        raise ComfyError(f"ComfyUI vrátilo HTTP {error.code}. {detail}".strip()) from error
    except URLError as error:
        raise ComfyError(f"S ComfyUI se nepodařilo spojit: {error.reason}") from error

    report("Animace byla uložena pro herního klienta.")
    return {"prompt_id": prompt_id, "motion_frames": frames, "duration_ms": duration,
            "active_path": str(active_path)}
