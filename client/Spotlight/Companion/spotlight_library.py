"""Store named Spotlight dances locally, separately for each character."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unicodedata import category
from uuid import uuid4

if __package__:
    from .spotlight_http import CLIP_ID, SLOT_MS, RelayError, read_clip, verify_clip
else:
    from spotlight_http import CLIP_ID, SLOT_MS, RelayError, read_clip, verify_clip


ENTRY_ID = re.compile(r"[0-9a-f]{32}")
MAX_NAME_LENGTH = 80
MAX_METADATA_BYTES = 4096
LOG = logging.getLogger(__name__)


class LibraryError(ValueError):
    """The library entry, clip, or user-supplied name is invalid."""


@dataclass(frozen=True)
class DanceEntry:
    clip_id: str
    name: str
    created_at: str
    duration_ms: int
    frames: int


def dance_name(value):
    if not isinstance(value, str):
        raise LibraryError("Enter a name for the dance.")
    value = value.strip()
    if (not 1 <= len(value) <= MAX_NAME_LENGTH
            or any(category(char) in ("Cc", "Cs", "Zl", "Zp") for char in value)):
        raise LibraryError(f"Use a dance name of 1 to {MAX_NAME_LENGTH} characters on one line.")
    return value


def inspect_motion(raw):
    try:
        digest = verify_clip(raw)
        # Replay reads UTF-8 text, so reject other JSON encodings here as well.
        frames = json.loads(raw.decode("utf-8"))["frames"]
    except (RelayError, RecursionError, ValueError) as error:
        raise LibraryError(f"Invalid library dance: {error}") from error
    return digest, frames[-1]["time_ms"], len(frames)


def metadata(entry, digest):
    return json.dumps({**asdict(entry), "sha256": digest}, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8") + b"\n"


class DanceLibrary:
    def __init__(self, client_dir, guid):
        if type(guid) is not int or not 0 < guid < 2**64:
            raise LibraryError("Log in to a character to use the Spotlight library.")
        self.directory = Path(client_dir) / "Spotlight" / "library" / f"{guid:016x}"

    def _entry_directory(self, clip_id):
        if not isinstance(clip_id, str) or not ENTRY_ID.fullmatch(clip_id):
            raise LibraryError("Invalid Spotlight library clip ID.")
        return self.directory / clip_id

    def _load(self, clip_id):
        directory = self._entry_directory(clip_id)
        try:
            with (directory / "metadata.json").open("rb") as stream:
                raw = stream.read(MAX_METADATA_BYTES + 1)
            if len(raw) > MAX_METADATA_BYTES:
                raise ValueError("Metadata file exceeds its size limit")
            if not (directory / "motion.json").is_file():
                raise ValueError("The entry has no motion file")
            data = json.loads(raw)
            created = datetime.fromisoformat(data["created_at"])
            duration, frames, digest = data["duration_ms"], data["frames"], data["sha256"]
            if (data["clip_id"] != clip_id or created.utcoffset() != timezone.utc.utcoffset(None)
                    or type(duration) is not int or not 0 < duration <= SLOT_MS
                    or type(frames) is not int or not 2 <= frames <= 1800
                    or not CLIP_ID.fullmatch(digest)):
                raise ValueError("Invalid metadata values")
            entry = DanceEntry(clip_id, dance_name(data["name"]), data["created_at"], duration, frames)
        except (KeyError, OSError, RecursionError, TypeError, ValueError) as error:
            raise LibraryError(f"Cannot read library dance {clip_id}.") from error
        return directory, entry, digest

    def entries(self):
        result = []
        for directory in self.directory.glob("*"):
            if not ENTRY_ID.fullmatch(directory.name):
                continue
            try:
                _, entry, _ = self._load(directory.name)
                result.append(entry)
            except LibraryError:
                LOG.warning("Skipping invalid Spotlight library entry %s.", directory.name)
        return sorted(result, key=lambda entry: (entry.created_at, entry.clip_id), reverse=True)

    def save(self, motion_path, name=None):
        return self._save(read_clip(motion_path), name)

    def import_dance(self, raw, name, expected_id):
        return self._save(raw, name, expected_id=expected_id)

    def _save(self, raw, name, *, expected_id=None):
        now = datetime.now(timezone.utc)
        name = dance_name(name) if name is not None else f"Dance {now.astimezone():%Y-%m-%d %H:%M:%S}"
        digest, duration, frames = inspect_motion(raw)
        if expected_id is not None:
            if digest != expected_id:
                raise LibraryError("The downloaded dance does not match its gallery ID.")
            for directory in self.directory.glob("*"):
                if not ENTRY_ID.fullmatch(directory.name):
                    continue
                try:
                    _, existing, existing_digest = self._load(directory.name)
                    if existing_digest == digest:
                        self.path_for(existing.clip_id)
                        return existing
                except LibraryError:
                    continue
        entry = DanceEntry(uuid4().hex, name, now.isoformat(timespec="milliseconds"),
                           duration, frames)
        self.directory.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="staging-", dir=self.directory) as work:
            staged = Path(work)
            (staged / "motion.json").write_bytes(raw)
            (staged / "metadata.json").write_bytes(metadata(entry, digest))
            staged.rename(self._entry_directory(entry.clip_id))
        return entry

    def rename(self, clip_id, name):
        name = dance_name(name)
        directory, entry, digest = self._load(clip_id)
        if entry.name == name:
            return entry
        entry = DanceEntry(clip_id, name, entry.created_at, entry.duration_ms, entry.frames)
        staged = None
        try:
            with NamedTemporaryFile(dir=directory, delete=False) as stream:
                staged = Path(stream.name)
                stream.write(metadata(entry, digest))
            staged.replace(directory / "metadata.json")
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
        return entry

    def path_for(self, clip_id):
        directory, entry, digest = self._load(clip_id)
        path = directory / "motion.json"
        try:
            motion = inspect_motion(read_clip(path))
        except OSError as error:
            raise LibraryError(f"Cannot read the clip for dance {clip_id}.") from error
        if motion != (digest, entry.duration_ms, entry.frames):
            raise LibraryError(f"The clip for dance {clip_id} does not match its library metadata.")
        return path
