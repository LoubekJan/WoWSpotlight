"""Store and serve the motion files shared by ComfyUI and WoWSpotlight."""

import argparse
from contextlib import closing
from hashlib import sha256
from hmac import compare_digest
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
from time import time_ns
from urllib.parse import parse_qs, quote, unquote

from tools.dance_capture.spotlight_http import CLIP_ID, MAX_CLIP_BYTES
from tools.dance_capture.spotlight_library import LibraryError, dance_name, inspect_motion


PAGE_SIZE = 6
TOKEN = re.compile(r"[A-Za-z0-9_-]{16,128}")
NAME_HEADER = "X-Spotlight-Dance-Name"
WEB = Path(__file__).resolve().parent / "web"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
LOG = logging.getLogger(__name__)


class RequestError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Gallery:
    def __init__(self, data_dir, token):
        if not TOKEN.fullmatch(token):
            raise ValueError("Configure a gallery token of 16–128 ASCII letters, digits, underscores or dashes.")
        data_dir.mkdir(parents=True, exist_ok=True)
        self.database = data_dir / "gallery.sqlite3"
        self.token = token.encode("ascii")
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS dances (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at_ms INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL, motion BLOB NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS dances_created ON dances (created_at_ms DESC, id DESC)")

    def connect(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        return db

    def authorize(self, header):
        scheme, _, value = header.partition(" ")
        if (scheme.lower() != "bearer" or not TOKEN.fullmatch(value)
                or not compare_digest(value.encode("ascii"), self.token)):
            raise RequestError(HTTPStatus.UNAUTHORIZED, "A valid gallery publishing token is required.")

    def publish(self, raw, name):
        try:
            clip_id, duration, _ = inspect_motion(raw)
        except LibraryError as error:
            raise RequestError(HTTPStatus.BAD_REQUEST, "Invalid Spotlight HumanMale dance.") from error
        created = time_ns() // 1_000_000
        with closing(self.connect()) as db, db:
            cursor = db.execute("""INSERT INTO dances (id, name, created_at_ms, duration_ms, motion)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING""", (clip_id, name, created, duration, raw))
            inserted = cursor.rowcount == 1
            row = db.execute("SELECT id, name, created_at_ms, duration_ms FROM dances WHERE id = ?",
                             (clip_id,)).fetchone()
        return dict(row), inserted

    def page(self, page):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            count = db.execute("SELECT count(*) FROM dances").fetchone()[0]
            pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
            page = min(page, pages)
            rows = db.execute("""SELECT id, name, created_at_ms, duration_ms FROM dances
                ORDER BY created_at_ms DESC, id DESC LIMIT ? OFFSET ?""", (PAGE_SIZE, (page - 1) * PAGE_SIZE))
            return {"items": [dict(row) for row in rows], "page": page, "pages": pages}

    def download(self, clip_id):
        if not CLIP_ID.fullmatch(clip_id):
            raise RequestError(HTTPStatus.NOT_FOUND, "Dance not found.")
        with closing(self.connect()) as db:
            row = db.execute("SELECT name, motion FROM dances WHERE id = ?", (clip_id,)).fetchone()
        if row is None:
            raise RequestError(HTTPStatus.NOT_FOUND, "Dance not found.")
        raw = row["motion"]
        if not isinstance(raw, bytes) or len(raw) > MAX_CLIP_BYTES or sha256(raw).hexdigest() != clip_id:
            raise RequestError(HTTPStatus.INTERNAL_SERVER_ERROR, "Stored dance failed its content check.")
        return raw, row["name"]


class GalleryHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(10)
        super().setup()

    def reply(self, status, raw, content_type, *, cache="no-store", headers=()):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def json_reply(self, status, value):
        self.reply(status, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        try:
            self.get()
        except RequestError as error:
            self.json_reply(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, sqlite3.Error):
            LOG.exception("Could not read gallery data")
            self.json_reply(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not read gallery data."})

    do_HEAD = do_GET

    def get(self):
        path, _, query = self.path.partition("?")
        if path in STATIC:
            filename, content_type = STATIC[path]
            self.reply(HTTPStatus.OK, (WEB / filename).read_bytes(), content_type, cache="no-cache")
        elif path == "/healthz":
            self.json_reply(HTTPStatus.OK, {"status": "ok"})
        elif path == "/api/dances":
            pages = parse_qs(query, keep_blank_values=True).get("page", ["1"])
            if len(pages) != 1 or not re.fullmatch(r"[1-9][0-9]{0,8}", pages[0]):
                raise RequestError(HTTPStatus.BAD_REQUEST, "Use a positive page number.")
            self.json_reply(HTTPStatus.OK, self.server.gallery.page(int(pages[0])))
        elif path.startswith("/api/dances/"):
            clip_id = path.removeprefix("/api/dances/")
            raw, name = self.server.gallery.download(clip_id)
            self.reply(HTTPStatus.OK, raw, "application/json; charset=utf-8", cache="public, max-age=31536000, immutable",
                       headers=((NAME_HEADER, quote(name, safe="")),
                                ("Content-Disposition", f'attachment; filename="{clip_id}.motion.json"')))
        else:
            raise RequestError(HTTPStatus.NOT_FOUND, "Page not found.")

    def do_POST(self):
        try:
            self.post()
        except RequestError as error:
            self.json_reply(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, sqlite3.Error):
            LOG.exception("Could not store gallery dance")
            self.json_reply(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Could not store gallery dance."})

    def post(self):
        if self.path != "/api/dances":
            raise RequestError(HTTPStatus.NOT_FOUND, "Page not found.")
        self.server.gallery.authorize(self.headers.get("Authorization", ""))
        if self.headers.get_content_type() != "application/json":
            raise RequestError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Expected application/json.")
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"[1-9][0-9]{0,8}", lengths[0]):
            raise RequestError(HTTPStatus.LENGTH_REQUIRED, "Set the clip content length.")
        length = int(lengths[0])
        if length > MAX_CLIP_BYTES:
            raise RequestError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Dance exceeds the 8 MiB clip limit.")
        encoded_name = self.headers.get(NAME_HEADER, "")
        try:
            if len(encoded_name) > 960 or not encoded_name.isascii():
                raise ValueError("Invalid name header.")
            name = dance_name(unquote(encoded_name, errors="strict"))
        except ValueError as error:
            raise RequestError(HTTPStatus.BAD_REQUEST, "Provide a UTF-8 dance name of 1 to 80 characters.") from error
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise RequestError(HTTPStatus.BAD_REQUEST, "Incomplete dance file.")
        item, inserted = self.server.gallery.publish(raw, name)
        self.json_reply(HTTPStatus.CREATED if inserted else HTTPStatus.OK, item)

    def log_message(self, pattern, *args):
        LOG.info("%s - %s", self.client_address[0], pattern % args)


class GalleryServer(ThreadingHTTPServer):
    def __init__(self, address, gallery):
        super().__init__(address, GalleryHandler)
        self.gallery = gallery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        gallery = Gallery(args.data_dir, os.environ.get("SPOTLIGHT_GALLERY_TOKEN", ""))
        with GalleryServer((args.bind, args.port), gallery) as server:
            LOG.info("Spotlight gallery is listening on %s:%s", *server.server_address)
            server.serve_forever()
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Gallery failed: {error}\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
