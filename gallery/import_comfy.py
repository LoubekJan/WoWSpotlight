"""Publish finalized Spotlight motion files from a read-only ComfyUI output folder."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
import stat
from time import sleep
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener

from tools.dance_capture.spotlight_http import MAX_CLIP_BYTES, NoRedirect


OUTPUT_NAME = re.compile(r"([A-Za-z0-9_-]{1,64})-[a-f0-9]{12}\.motion\.json")
LOG = logging.getLogger(__name__)


class InvalidOutput(ValueError):
    pass


def clip_name(prefix, modified_at):
    if prefix in {"spotlight-companion", "spotlight-dance"}:
        captured = datetime.fromtimestamp(modified_at, tz=timezone.utc)
        return f"Tanec {captured:%d.%m.%Y %H:%M:%S} UTC"
    return prefix.replace("-", " ").replace("_", " ").strip() or "Tanec"


def read_output(path, observed):
    if observed.st_size > MAX_CLIP_BYTES:
        raise InvalidOutput("The motion file exceeds its size limit.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags | getattr(os, "O_BINARY", 0)), "rb") as source:
        current = os.fstat(source.fileno())
        if not stat.S_ISREG(current.st_mode) or not os.path.samestat(observed, current):
            raise OSError("The ComfyUI output changed during the scan.")
        data = source.read(MAX_CLIP_BYTES + 1)
    if len(data) > MAX_CLIP_BYTES:
        raise InvalidOutput("The motion file exceeds its size limit.")
    if len(data) != observed.st_size:
        raise OSError("The ComfyUI output size changed during the scan.")
    return data


class Importer:
    def __init__(self, source, gallery_url, token):
        self.source = source
        self.url = gallery_url.rstrip("/") + "/api/dances"
        self.token = token
        self.opener = build_opener(NoRedirect())
        self.processed = {}

    def upload(self, name, data, generated_at_ms):
        request = Request(self.url, data=data, headers={
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Spotlight-Dance-Name": quote(name, safe=""),
            "X-Spotlight-Generated-At-Ms": str(generated_at_ms),
        })
        try:
            with self.opener.open(request, timeout=10) as response:
                reply = json.loads(response.read(4096))
        except HTTPError as error:
            error.close()
            if error.code in (400, 413, 422):
                raise InvalidOutput(f"Gallery rejected the motion (HTTP {error.code}).") from error
            raise
        digest = sha256(data).hexdigest()
        if not isinstance(reply, dict) or reply.get("id") != digest:
            raise OSError("Gallery did not confirm the uploaded clip ID.")
        return digest

    def scan(self):
        candidates = []
        for path in self.source.iterdir():
            match = OUTPUT_NAME.fullmatch(path.name)
            if match is None:
                continue
            try:
                observed = path.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(observed.st_mode):
                candidates.append((path, observed, match[1]))

        current = {path for path, _, _ in candidates}
        self.processed = {path: stamp for path, stamp in self.processed.items() if path in current}
        for path, observed, prefix in sorted(candidates, key=lambda item: (item[1].st_mtime_ns, item[0].name)):
            stamp = (observed.st_ino, observed.st_mtime_ns, observed.st_size)
            if self.processed.get(path) == stamp:
                continue
            try:
                data = read_output(path, observed)
            except OSError as error:
                LOG.warning("Will retry ComfyUI output %s: %s", path.name, error)
                continue
            except InvalidOutput as error:
                LOG.warning("Skipped %s: %s", path.name, error)
            else:
                try:
                    digest = self.upload(clip_name(prefix, observed.st_mtime), data,
                                         observed.st_mtime_ns // 1_000_000)
                except InvalidOutput as error:
                    LOG.warning("Skipped %s: %s", path.name, error)
                else:
                    LOG.info("Gallery accepted %s as %s", path.name, digest)
            self.processed[path] = stamp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--gallery-url", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("SPOTLIGHT_GALLERY_TOKEN")
    if not token:
        parser.error("Set SPOTLIGHT_GALLERY_TOKEN for the importer.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    importer = Importer(args.source, args.gallery_url, token)
    while True:
        try:
            importer.scan()
        except (OSError, ValueError) as error:
            LOG.warning("ComfyUI gallery import could not finish: %s", error)
            if args.once:
                return 1
        if args.once:
            return 0
        sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
