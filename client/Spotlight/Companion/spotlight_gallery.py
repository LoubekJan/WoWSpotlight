"""Browse and download content-addressed motion clips from the shared gallery."""

from dataclasses import dataclass
import json
from urllib.parse import unquote, urlsplit
from urllib.request import build_opener

if __package__:
    from .spotlight_http import CLIP_ID, MAX_CLIP_BYTES, NoRedirect
    from .spotlight_library import dance_name
else:
    from spotlight_http import CLIP_ID, MAX_CLIP_BYTES, NoRedirect
    from spotlight_library import dance_name


PAGE_SIZE = 6


@dataclass(frozen=True)
class GalleryDance:
    clip_id: str
    name: str


class Gallery:
    def __init__(self, url):
        url = url.rstrip("/")
        parsed = urlsplit(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.query or parsed.fragment):
            raise ValueError("Supply an HTTP or HTTPS address for the Spotlight gallery.")
        self.url = url + "/api/dances"
        self.opener = build_opener(NoRedirect())

    def list(self, page):
        with self.opener.open(f"{self.url}?page={page}", timeout=5) as response:
            raw = response.read(16_385)
        try:
            if len(raw) > 16_384:
                raise ValueError("Page exceeds its size limit")
            data = json.loads(raw)
            page, pages, items = data["page"], data["pages"], data["items"]
            if (type(page) is not int or type(pages) is not int or not 1 <= page <= pages <= 2**31 - 1
                    or not isinstance(items, list) or len(items) > PAGE_SIZE):
                raise ValueError("Invalid page")
            dances = [GalleryDance(item["id"], dance_name(item["name"])) for item in items]
            if any(not CLIP_ID.fullmatch(dance.clip_id) for dance in dances):
                raise ValueError("Invalid dance ID")
        except (KeyError, RecursionError, TypeError, ValueError) as error:
            raise ValueError("The Spotlight gallery returned an invalid page.") from error
        return page, pages, dances

    def download(self, clip_id):
        if not CLIP_ID.fullmatch(clip_id):
            raise ValueError("Invalid Spotlight gallery dance ID.")
        with self.opener.open(f"{self.url}/{clip_id}", timeout=8) as response:
            name = dance_name(unquote(response.headers.get("X-Spotlight-Dance-Name", ""), errors="strict"))
            raw = response.read(MAX_CLIP_BYTES + 1)
        return name, raw
