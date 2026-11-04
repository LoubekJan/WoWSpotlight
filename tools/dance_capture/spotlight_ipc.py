"""Small fixed protocol between the Spotlight add-on and its Windows companion."""

from math import ceil


PALETTE = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 255))
SIGNALS = {
    (0, 1, 2, 3): "upload",
    (3, 2, 1, 0): "play",
    (0, 2, 3, 1): "list",
    (1, 0, 3, 2): "load",
    (2, 3, 0, 1): "rename",
    (3, 0, 1, 2): "retry",
    (1, 3, 0, 2): "receive",
    (0, 3, 1, 2): "gallery",
    (3, 1, 2, 0): "download",
}
PAYLOAD_SIGNALS = {"list", "load", "rename", "retry", "gallery", "download"}
STOCK_DANCE_SIGNAL = (2, 1, 0, 3)
COLUMNS = 48
MAX_NAME_BYTES = 96
MAX_REQUEST_BYTES = 32 + 1 + MAX_NAME_BYTES
MAX_REPLY_BYTES = 2_048
PAGE_SIZE = 4


def payload_position(cell):
    return (1 + cell % COLUMNS) / 100, 0.04 + (cell // COLUMNS) * 0.012


PAYLOAD_WIDTH = COLUMNS / 100
PAYLOAD_HEIGHT = payload_position((MAX_REQUEST_BYTES + 2) * 4 - 1)[1]


def color_index(pixel):
    if pixel == 0xFFFFFFFF:  # CLR_INVALID
        return None
    rgb = tuple((pixel >> shift) & 255 for shift in (0, 8, 16))
    return next((index for index, expected in enumerate(PALETTE)
                 if all(abs(a - b) <= 45 for a, b in zip(rgb, expected))), None)


def read_payload(sample):
    def read_byte(index):
        value = 0
        for offset in range(4):
            cell = index * 4 + offset
            symbol = sample(*payload_position(cell))
            if symbol is None:
                raise ValueError("Incomplete Spotlight signal")
            value = (value << 2) | symbol
        return value

    length = (read_byte(0) << 8) | read_byte(1)
    if length > MAX_REQUEST_BYTES:
        raise ValueError("Spotlight request exceeds its size limit")
    return bytes(read_byte(index + 2) for index in range(length)).decode("utf-8")


def hex_field(value):
    # The wire budget counts UTF-8 bytes, including Czech characters.
    return value.encode("utf-8")[:MAX_NAME_BYTES].decode("utf-8", "ignore").encode("utf-8").hex()


def library_reply(entries, page, loaded, retryable):
    page_count = max(1, ceil(len(entries) / PAGE_SIZE))
    page = min(max(1, page), page_count)
    rows = entries[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    header = f"library|{page}|{page_count}|{loaded or ''}|{int(retryable)}"
    return "~".join([header, *(f"{entry.clip_id}|{entry.duration_ms}|{hex_field(entry.name)}" for entry in rows)])


def error_reply(message, retryable):
    return f"error|{int(retryable)}|{hex_field(message)}"


def gallery_reply(page, pages, dances):
    return "~".join([f"gallery|{page}|{pages}",
                     *(f"{dance.clip_id}|{hex_field(dance.name)}" for dance in dances)])
