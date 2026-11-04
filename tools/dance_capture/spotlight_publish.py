"""Publish a prepared dance while its actor plays the native WoW dance emote."""

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event
from time import monotonic
from urllib.error import URLError
from uuid import uuid4

if __package__:
    from . import duet_select, runtime_poc
    from .spotlight_http import Relay, RelayError
else:
    import duet_select
    import runtime_poc
    from spotlight_http import Relay, RelayError


DANCE_EMOTE = 10
POLL_SECONDS = 0.2
REFRESH_SECONDS = 5
READ_ERRORS = (OSError, ValueError)
NETWORK_ERRORS = (OSError, RelayError, URLError)


@dataclass(frozen=True)
class Publication:
    guid: int
    clip_id: str
    event_id: str


def local_dance(process):
    manager = duet_select.object_manager(process)
    guid = duet_select.active_guid(process)
    unit = duet_select.lookup_unit(process, manager, guid) if guid else 0
    emote, stand = duet_select.unit_emote(process, unit)
    return guid, emote == DANCE_EMOTE and stand == 0


def read_token(path):
    token = Path(path).read_text(encoding="ascii").strip()
    if not 16 <= len(token) <= 128 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in token):
        raise ValueError("The actor token file must contain one valid relay token.")
    return token


class Publisher:
    def __init__(self, relay, *, follow_emote=False):
        self.relay = relay
        self.follow_emote = follow_emote
        self.requests = SimpleQueue()
        self.closed = Event()

    def prepare(self, guid, clip_id):
        self.requests.put(("prepare", (guid, clip_id)))

    def play(self):
        self.requests.put(("play", None))

    def close(self):
        self.closed.set()

    def stop(self, publication):
        try:
            self.relay.stop(publication.guid, publication.event_id)
        except NETWORK_ERRORS as error:
            logging.warning("Could not end shared dance immediately: %s", error)
        else:
            logging.info("Stopped shared dance %s.", publication.event_id)

    def watch(self, pid, executable):
        prepared = current = pending = None
        publish_after = pending_until = 0.0
        was_dancing = False
        try:
            with runtime_poc.ClientProcess(pid, executable, rights=duet_select.PROCESS_READ_RIGHTS) as process:
                while not self.closed.is_set():
                    try:
                        guid, dancing = local_dance(process)
                    except READ_ERRORS:
                        if process.read(duet_select.IMAGE_BASE, 2) != b"MZ" or self.closed.wait(POLL_SECONDS):
                            break
                        continue
                    play = self.follow_emote and dancing and not was_dancing
                    was_dancing = dancing
                    while True:
                        try:
                            command, value = self.requests.get_nowait()
                        except Empty:
                            break
                        if command == "prepare":
                            prepared = value
                        else:
                            play = True
                    now = monotonic()
                    if (play and prepared and prepared[0] == guid and pending is None
                            and (current is None or (current.guid, current.clip_id) != prepared)):
                        pending = Publication(guid, prepared[1], uuid4().hex)
                        pending_until = now + 5
                        publish_after = now
                    if current and (current.guid != guid or not dancing):
                        self.stop(current)
                        current = None
                    if pending and (pending.guid != guid or not dancing and now >= pending_until):
                        self.stop(pending)
                        pending = None
                    publication = pending or current
                    if publication and dancing and now >= publish_after:
                        try:
                            reply = self.relay.start(publication.guid, publication.clip_id, publication.event_id)
                            if reply.get("event_id") != publication.event_id:
                                raise RelayError("The relay did not confirm the dance.")
                        except NETWORK_ERRORS as error:
                            if isinstance(error, RelayError) and error.code in (401, 403, 409):
                                logging.error("Shared dance rejected: %s", error)
                                pending = current = None
                            else:
                                logging.warning("Could not publish shared dance: %s", error)
                            publish_after = now + 1
                        else:
                            if publication != current:
                                logging.info("Published dance %s for 0x%016X.", publication.event_id, publication.guid)
                            current, pending = publication, None
                            publish_after = now + REFRESH_SECONDS
                    self.closed.wait(POLL_SECONDS)
        except READ_ERRORS as error:
            logging.error("Spotlight publisher could not attach: %s", error)
        finally:
            if pending and pending != current:
                self.stop(pending)
            if current:
                self.stop(current)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int)
    parser.add_argument("clip", type=Path)
    parser.add_argument("--client-dir", type=Path, required=True)
    parser.add_argument("--relay-url", default="http://127.0.0.1:8765")
    parser.add_argument("--relay-token-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        executable = duet_select.verified_executable(args.client_dir.resolve())
        relay = Relay(args.relay_url, read_token(args.relay_token_file))
        with runtime_poc.ClientProcess(args.pid, executable, rights=duet_select.PROCESS_READ_RIGHTS) as process:
            guid = duet_select.active_guid(process)
        if not guid:
            raise ValueError("Enter the world on this actor before starting the publisher.")
        publisher = Publisher(relay, follow_emote=True)
        publisher.prepare(guid, relay.upload(args.clip))
    except (*READ_ERRORS, *NETWORK_ERRORS) as error:
        parser.exit(1, f"Spotlight publisher failed: {error}\n")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("Ready for /dance on 0x%016X.", guid)
    try:
        publisher.watch(args.pid, executable)
    except KeyboardInterrupt:
        publisher.close()


if __name__ == "__main__":
    main()
