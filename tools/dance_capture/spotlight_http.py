"""HTTP client and local clip cache for the Spotlight relay."""

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from time import monotonic
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

if __package__:
    from .client_poc import FULL_BODY_FORMAT, full_body_motion
else:
    from client_poc import FULL_BODY_FORMAT, full_body_motion


SLOT_MS = 17_700
MAX_CLIP_BYTES = 8 * 1024 * 1024
MAX_STATE_BYTES = 64 * 1024
CLIP_ID = re.compile(r"[0-9a-f]{64}")
EVENT_ID = re.compile(r"[0-9a-f]{32}")
GUID = re.compile(r"0x[0-9a-f]{16}")


class RelayError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        return None


@dataclass(frozen=True)
class DanceEvent:
    guid: int
    clip_id: str
    event_id: str
    started_at_ms: int
    expires_at_ms: int


@dataclass(frozen=True)
class DanceState:
    events: tuple[DanceEvent, ...]
    server_time_ms: int
    sample_time: float

    def now_ms(self):
        return self.server_time_ms + round((monotonic() - self.sample_time) * 1000)


def read_clip(path):
    with Path(path).open("rb") as stream:
        return stream.read(MAX_CLIP_BYTES + 1)


def verify_clip(data):
    if not 0 < len(data) <= MAX_CLIP_BYTES:
        raise RelayError("The shared dance file exceeds the clip limit.")
    try:
        motion = json.loads(data)
        if motion.get("format") != FULL_BODY_FORMAT:
            raise ValueError("Expected a Spotlight motion file")
        full_body_motion(motion, SLOT_MS)
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError) as error:
        raise RelayError(f"Invalid shared dance: {error}") from error
    return sha256(data).hexdigest()


class Relay:
    def __init__(self, base_url, token=None):
        base_url = base_url.rstrip("/")
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.query or parsed.fragment):
            raise ValueError("Supply an HTTP or HTTPS address for the Spotlight relay.")
        self.base_url = base_url
        self.token = token
        self.opener = build_opener(NoRedirect())

    def request(self, path, data=None, *, raw=False, limit=MAX_STATE_BYTES):
        headers = {}
        if data is not None:
            if not self.token:
                raise RelayError("An actor token is required to publish a dance.")
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            if not isinstance(data, bytes):
                data = json.dumps(data, separators=(",", ":")).encode("ascii")
        request = Request(self.base_url + path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=3) as response:
                body = response.read(limit + 1)
        except HTTPError as error:
            with error:
                detail = error.read(512).decode("utf-8", "replace").strip()
            raise RelayError(f"Spotlight relay returned HTTP {error.code}. {detail}", error.code) from error
        if len(body) > limit:
            raise RelayError("Spotlight relay response exceeded its size limit.")
        if raw:
            return body
        try:
            value = json.loads(body)
        except (UnicodeError, ValueError) as error:
            raise RelayError("Spotlight relay returned invalid JSON.") from error
        if not isinstance(value, dict):
            raise RelayError("Spotlight relay returned an unexpected response.")
        return value

    def upload(self, path):
        data = read_clip(path)
        clip_id = verify_clip(data)
        if self.request("/clips", data).get("clip_id") != clip_id:
            raise RelayError("Spotlight relay did not confirm this clip.")
        return clip_id

    def start(self, guid, clip_id, event_id):
        return self.request(f"/actors/0x{guid:016x}/start", {"clip_id": clip_id, "event_id": event_id})

    def stop(self, guid, event_id):
        return self.request(f"/actors/0x{guid:016x}/stop", {"event_id": event_id})

    def state(self):
        before = monotonic()
        body = self.request("/state")
        sample = (before + monotonic()) / 2
        try:
            server_time = body["server_time_ms"]
            records = body["actors"]
            if type(server_time) is not int or server_time <= 0 or not isinstance(records, list):
                raise ValueError("Invalid server clock or actor list")
            events = {}
            for actor in records:
                name, clip, event = actor["actor_guid"], actor["clip_id"], actor["event_id"]
                start, end = actor["started_at_ms"], actor["expires_at_ms"]
                if (not GUID.fullmatch(name) or not CLIP_ID.fullmatch(clip) or not EVENT_ID.fullmatch(event)
                        or type(start) is not int or type(end) is not int or not 0 < start <= server_time < end):
                    raise ValueError("Invalid dance event")
                guid = int(name, 16)
                if not guid or guid in events:
                    raise ValueError("Duplicate or empty actor GUID")
                events[guid] = DanceEvent(guid, clip, event, start, end)
        except (KeyError, TypeError, ValueError) as error:
            raise RelayError(f"Invalid relay state: {error}") from error
        return DanceState(tuple(events.values()), server_time, sample)

    def cached_clip(self, directory, clip_id):
        if not CLIP_ID.fullmatch(clip_id):
            raise RelayError("Invalid clip ID.")
        path = directory / f"{clip_id}.motion.json"
        try:
            if verify_clip(read_clip(path)) == clip_id:
                return path
        except (FileNotFoundError, RelayError):
            pass
        data = self.request(f"/clips/{clip_id}", raw=True, limit=MAX_CLIP_BYTES)
        if verify_clip(data) != clip_id:
            raise RelayError("Downloaded animation did not match its clip ID.")
        directory.mkdir(parents=True, exist_ok=True)
        staged = None
        try:
            with NamedTemporaryFile(dir=directory, delete=False) as stream:
                staged = Path(stream.name)
                stream.write(data)
            staged.replace(path)
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
        return path
