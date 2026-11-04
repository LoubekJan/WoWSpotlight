"""Serve Spotlight clips and active dances for a trusted test realm."""

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
from hmac import compare_digest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from threading import Lock
import time

if __package__:
    from .client_poc import FULL_BODY_FORMAT, full_body_motion
    from .spotlight_comfy import SLOT_DURATION_MS
else:
    from client_poc import FULL_BODY_FORMAT, full_body_motion
    from spotlight_comfy import SLOT_DURATION_MS


MAX_CLIP_BYTES = 8 * 1024 * 1024
MAX_CONTROL_BYTES = 1024
DEFAULT_LEASE_MS = 60_000
RETAINED_EVENTS_PER_ACTOR = 64
CLIP_ID = re.compile(r"[0-9a-f]{64}")
EVENT_ID = re.compile(r"[0-9a-f]{32}")
ACTOR_ROUTE = re.compile(r"/actors/([^/]+)/(start|stop)")
TOKEN = re.compile(r"[A-Za-z0-9_-]{16,128}")
LOG = logging.getLogger("spotlight.relay")


class RelayError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def normalize_guid(value):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{16}", value) or int(value, 16) == 0:
        raise ValueError("Use a nonzero GUID as 0x followed by 16 hexadecimal digits.")
    return value.lower()


def reject_constant(value):
    raise ValueError(f"Unexpected JSON constant: {value}")


def load_object(raw):
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except (ValueError, RecursionError) as error:
        raise RelayError(HTTPStatus.BAD_REQUEST, "Expected a UTF-8 JSON object.") from error
    if not isinstance(value, dict):
        raise RelayError(HTTPStatus.BAD_REQUEST, "Expected a JSON object.")
    return value


def read_id(value, pattern, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise RelayError(HTTPStatus.BAD_REQUEST, f"Invalid {label}.")
    return value


def load_actor_tokens(path):
    config = load_object(path.read_bytes())
    actors = {}
    tokens = set()
    for key, token in config.items():
        guid = normalize_guid(key)
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise ValueError("Each actor token must contain 16–128 letters, digits, underscores or dashes.")
        if guid in actors or token in tokens:
            raise ValueError("Use a separate token for each actor.")
        actors[guid] = token.encode("ascii")
        tokens.add(token)
    if not actors:
        raise ValueError("Configure at least one actor token.")
    return actors


@dataclass
class Dance:
    actor_guid: str
    clip_id: str
    event_id: str
    duration_ms: int
    started_at_ms: int
    expires_at_ms: int


class Relay:
    def __init__(self, data_dir, actors, lease_ms=DEFAULT_LEASE_MS):
        self.clip_dir = data_dir / "clips"
        self.clip_dir.mkdir(parents=True, exist_ok=True)
        self.actors = actors
        self.lease_ms = lease_ms
        self.active = {}
        self.recent = {actor: {} for actor in actors}
        self.lock = Lock()
        self.wall_origin = time.time_ns()
        self.clock_origin = time.monotonic_ns()

    def now_ms(self):
        elapsed = time.monotonic_ns() - self.clock_origin
        return (self.wall_origin + elapsed) // 1_000_000

    def authorize(self, header, actor=None):
        prefix, _, value = header.partition(" ")
        if prefix.lower() != "bearer" or not TOKEN.fullmatch(value):
            raise RelayError(HTTPStatus.UNAUTHORIZED, "An actor token is required.")
        supplied = value.encode("ascii")
        expected = self.actors.values() if actor is None else (self.actors.get(actor, b""),)
        if not any(compare_digest(supplied, token) for token in expected):
            raise RelayError(HTTPStatus.UNAUTHORIZED, "Invalid actor token.")

    def clip_path(self, clip_id):
        return self.clip_dir / f"{clip_id}.json"

    def upload(self, raw):
        motion = load_object(raw)
        try:
            if motion.get("format") != FULL_BODY_FORMAT:
                raise ValueError("Expected Spotlight motion format.")
            timestamps, _ = full_body_motion(motion, SLOT_DURATION_MS)
        except (IndexError, KeyError, TypeError, ValueError, OverflowError) as error:
            raise RelayError(HTTPStatus.BAD_REQUEST, "Invalid Spotlight HumanMale clip.") from error

        clip_id = sha256(raw).hexdigest()
        path = self.clip_path(clip_id)
        if not path.is_file():
            staged = None
            try:
                with NamedTemporaryFile(dir=self.clip_dir, delete=False) as stream:
                    staged = Path(stream.name)
                    stream.write(raw)
                with self.lock:
                    if not path.is_file():
                        staged.replace(path)
            finally:
                if staged is not None:
                    staged.unlink(missing_ok=True)
        return {"clip_id": clip_id, "duration_ms": timestamps[-1]}

    def download(self, clip_id):
        try:
            with self.clip_path(clip_id).open("rb") as stream:
                raw = stream.read(MAX_CLIP_BYTES + 1)
        except FileNotFoundError as error:
            raise RelayError(HTTPStatus.NOT_FOUND, "Clip not found.") from error
        if len(raw) > MAX_CLIP_BYTES or sha256(raw).hexdigest() != clip_id:
            raise RelayError(HTTPStatus.INTERNAL_SERVER_ERROR, "Stored clip failed its content check.")
        return raw

    def active_dance(self, actor, now):
        dance = self.active.get(actor)
        if dance is not None and dance.expires_at_ms <= now:
            del self.active[actor]
            return None
        return dance

    def repeat_start(self, actor, clip_id, event_id, now):
        previous = self.recent[actor].get(event_id)
        if previous is None:
            return None
        if previous.clip_id != clip_id or self.active_dance(actor, now) is not previous:
            raise RelayError(HTTPStatus.CONFLICT, "This dance event cannot be restarted.")
        previous.expires_at_ms = now + self.lease_ms
        return asdict(previous)

    def start(self, actor, clip_id, event_id):
        with self.lock:
            repeated = self.repeat_start(actor, clip_id, event_id, self.now_ms())
            if repeated is not None:
                return repeated
        # Read only a previously validated, content-addressed clip.
        motion = load_object(self.download(clip_id))
        duration_ms = motion["frames"][-1]["time_ms"]
        with self.lock:
            now = self.now_ms()
            repeated = self.repeat_start(actor, clip_id, event_id, now)
            if repeated is not None:
                return repeated
            dance = Dance(actor, clip_id, event_id, duration_ms, now, now + self.lease_ms)
            self.active[actor] = dance
            recent = self.recent[actor]
            recent[event_id] = dance
            if len(recent) > RETAINED_EVENTS_PER_ACTOR:
                del recent[next(iter(recent))]
            return asdict(dance)

    def stop(self, actor, event_id):
        with self.lock:
            dance = self.active_dance(actor, self.now_ms())
            if dance is None or dance.event_id != event_id:
                return {"stopped": False}
            del self.active[actor]
            return {"stopped": True}

    def state(self):
        with self.lock:
            now = self.now_ms()
            active = (self.active_dance(actor, now) for actor in sorted(self.active))
            return {"server_time_ms": now, "actors": [asdict(dance) for dance in active if dance is not None]}


class RelayHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(10)
        super().setup()

    def log_message(self, *args):
        # A polling observer fetches state continually. Log actual server errors only.
        return

    def read_body(self, limit):
        values = self.headers.get_all("Content-Length", ())
        if len(values) != 1 or self.headers.get("Transfer-Encoding") or not re.fullmatch(r"[0-9]{1,10}", values[0]):
            raise RelayError(HTTPStatus.LENGTH_REQUIRED, "A Content-Length header is required.")
        length = int(values[0])
        if length > limit:
            raise RelayError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body is too large.")
        body = self.rfile.read(length)
        if len(body) != length:
            raise RelayError(HTTPStatus.BAD_REQUEST, "Incomplete request body.")
        return body

    def get(self):
        relay = self.server.relay
        if self.path == "/state":
            return HTTPStatus.OK, relay.state()
        if self.path.startswith("/clips/") and CLIP_ID.fullmatch(self.path[7:]):
            return HTTPStatus.OK, relay.download(self.path[7:])
        raise RelayError(HTTPStatus.NOT_FOUND, "Route not found.")

    def post(self):
        relay = self.server.relay
        auth = self.headers.get("Authorization", "")
        if self.path == "/clips":
            relay.authorize(auth)
            return HTTPStatus.CREATED, relay.upload(self.read_body(MAX_CLIP_BYTES))
        route = ACTOR_ROUTE.fullmatch(self.path)
        if route is None:
            raise RelayError(HTTPStatus.NOT_FOUND, "Route not found.")
        try:
            actor = normalize_guid(route[1])
        except ValueError as error:
            raise RelayError(HTTPStatus.BAD_REQUEST, str(error)) from error
        relay.authorize(auth, actor)
        body = load_object(self.read_body(MAX_CONTROL_BYTES))
        event_id = read_id(body.get("event_id"), EVENT_ID, "event ID")
        if route[2] == "stop":
            return HTTPStatus.OK, relay.stop(actor, event_id)
        clip_id = read_id(body.get("clip_id"), CLIP_ID, "clip ID")
        return HTTPStatus.OK, relay.start(actor, clip_id, event_id)

    def dispatch(self, action):
        try:
            status, body = action()
        except RelayError as error:
            status, body = error.status, {"error": str(error)}
        except TimeoutError:
            status, body = HTTPStatus.REQUEST_TIMEOUT, {"error": "Request timed out."}
        except OSError:
            LOG.exception("Spotlight relay request failed")
            status, body = HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Relay storage error."}
        if not isinstance(body, bytes):
            body = json.dumps(body, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, TimeoutError):
            return

    def do_GET(self):
        self.dispatch(self.get)

    def do_POST(self):
        self.dispatch(self.post)


class RelayServer(ThreadingHTTPServer):
    def __init__(self, address, relay):
        self.relay = relay
        super().__init__(address, RelayHandler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, required=True, help="Directory for persisted clip files")
    parser.add_argument("--actors", type=Path, required=True, help="JSON file mapping actor GUIDs to tokens")
    parser.add_argument("--lease-ms", type=int, default=DEFAULT_LEASE_MS)
    args = parser.parse_args()
    if not 1_000 <= args.lease_ms <= 300_000:
        parser.error("Use a lease between 1,000 and 300,000 milliseconds.")
    logging.basicConfig(level=logging.INFO)
    try:
        relay = Relay(args.data_dir, load_actor_tokens(args.actors), args.lease_ms)
        with RelayServer((args.bind, args.port), relay) as server:
            LOG.info("Spotlight relay listening on %s:%s", *server.server_address)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as error:
        parser.exit(1, f"Spotlight relay failed: {error}\n")


if __name__ == "__main__":
    main()
