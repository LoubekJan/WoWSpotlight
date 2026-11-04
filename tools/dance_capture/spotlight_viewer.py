"""Download and play the active dances near an isolated Spotlight observer."""

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import logging
from pathlib import Path
from time import monotonic, sleep
from urllib.error import URLError

if __package__:
    from . import client_poc, duet_assets, duet_runtime, duet_select, runtime_poc
    from .spotlight_http import SLOT_MS, DanceEvent, Relay, RelayError
else:
    import client_poc
    import duet_assets
    import duet_runtime
    import duet_select
    import runtime_poc
    from spotlight_http import SLOT_MS, DanceEvent, Relay, RelayError


SLOTS = (client_poc.ANIMATION_ID, duet_assets.SECOND_ANIMATION_ID)
POLL_SECONDS = 0.3
NATIVE_DANCE = 10
STOCK_DANCE_ANIMATION = 69


def event_key(event):
    return event.guid, event.event_id, event.started_at_ms, event.clip_id


@dataclass
class Assignment:
    event: DanceEvent
    slot: int
    synced_model: str | None = None
    next_sync: float = 0.0


class Viewer:
    def __init__(self, process, runtime, relay, cache, *, slots=SLOTS):
        self.process = process
        self.runtime = runtime
        self.relay = relay
        self.cache = cache
        self.slots = slots
        self.local_guid = 0
        self.state = None
        self.assignments = {}
        self.observed_emotes = {}
        self.retired = {}
        self.configured = ()

    def configure(self):
        actors = [(guid, assignment.slot) for guid, assignment in self.assignments.items()]
        if self.local_guid:
            actors.append((self.local_guid, client_poc.ANIMATION_ID))
        actors = tuple(sorted(actors))
        if actors != self.configured:
            duet_select.configure(self.process, actors)
            self.configured = actors

    def release(self, manager):
        for slot, guid in tuple(self.retired.items()):
            snapshot = duet_select.actor_snapshot(self.process, manager, guid)
            if (snapshot.get("active_animation") != slot
                    or snapshot.get("emote_state") == NATIVE_DANCE
                    and duet_select.sync_actor(self.process, manager, guid, STOCK_DANCE_ANIMATION, 0)):
                del self.retired[slot]

    def tick(self):
        manager = duet_select.object_manager(self.process)
        observer = duet_select.active_guid(self.process)
        if observer:
            try:
                self.state = self.relay.state()
            except (OSError, RelayError, URLError) as error:
                logging.warning("Could not read Spotlight relay: %s", error)
        events, snapshots = {}, {}
        if observer and self.state:
            now_ms = self.state.now_ms()
            live_events = {event_key(event): event for event in self.state.events if event.expires_at_ms > now_ms}
            self.observed_emotes = {key: emote for key, emote in self.observed_emotes.items() if key in live_events}
            for key, event in live_events.items():
                guid = event.guid
                previous_emote = self.observed_emotes.get(key)
                if guid == observer or (previous_emote is not None and previous_emote != NATIVE_DANCE):
                    continue
                if not duet_select.lookup_unit(self.process, manager, guid):
                    continue
                if previous_emote == NATIVE_DANCE:
                    snapshot = duet_select.actor_snapshot(self.process, manager, guid)
                    emote = snapshot.get("emote_state")
                    if emote is not None and emote != NATIVE_DANCE:
                        self.observed_emotes[key] = emote
                        logging.info("Observed the end of Spotlight event %s for 0x%016X.", event.event_id, guid)
                        continue
                    snapshots[guid] = snapshot
                events[guid] = event

        for guid, assignment in tuple(self.assignments.items()):
            event = events.get(guid)
            if event is None or event_key(event) != event_key(assignment.event):
                self.retired[assignment.slot] = guid
                del self.assignments[guid]
        self.configure()
        self.release(manager)

        for guid, event in events.items():
            if guid not in self.assignments:
                if guid in self.retired.values():
                    continue  # Wait until the old native sequence has released its slot.
                free = next((slot for slot in self.slots
                             if slot not in self.retired
                             and all(a.slot != slot for a in self.assignments.values())), None)
                if free is None:
                    continue
                try:
                    clip = self.relay.cached_clip(self.cache, event.clip_id)
                    report = self.runtime.apply(free, clip)
                    logging.info("Loaded event %s clip %s for 0x%016X in slot %d, baked SHA-256 %s.",
                                 event.event_id, event.clip_id, guid, free, report["animation_sha256"])
                except (OSError, RelayError, URLError, runtime_poc.TrackNotReadyError) as error:
                    logging.debug("Waiting for clip/slot %d: %s", free, error)
                    continue
                if event.expires_at_ms <= self.state.now_ms():
                    continue
                self.assignments[guid] = Assignment(event, free)
                self.configure()
            assignment = self.assignments[guid]
            snapshot = snapshots.get(guid)
            if snapshot is None:
                snapshot = duet_select.actor_snapshot(self.process, manager, guid)
            model = snapshot.get("model")
            dancing = snapshot.get("emote_state") == NATIVE_DANCE and snapshot.get("stand_state") == 0
            if dancing:
                self.observed_emotes[event_key(event)] = NATIVE_DANCE
            if not model or not dancing:
                assignment.synced_model = None
                continue
            if (model != assignment.synced_model or snapshot.get("active_animation") != assignment.slot):
                now = monotonic()
                if now < assignment.next_sync:
                    continue
                assignment.next_sync = now + 0.5
                phase = max(0, self.state.now_ms() - event.started_at_ms) % SLOT_MS
                if duet_select.sync_actor(self.process, manager, guid, assignment.slot, phase):
                    assignment.synced_model = model
                    logging.info("Playing %s for 0x%016X in slot %d from %d ms.",
                                 event.event_id, guid, assignment.slot, phase)


@contextmanager
def exclusive_viewer(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = duet_select.bind(kernel, "CreateMutexW", wintypes.HANDLE,
                              ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    close = duet_select.bind(kernel, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    ctypes.set_last_error(0)
    handle = duet_select.checked(create(None, False, f"Local\\WoWSpotlight-Viewer-{pid}"))
    try:
        if ctypes.get_last_error() == 183:
            raise ValueError("A Spotlight viewer is already following this client.")
        yield
    finally:
        close(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int, help="PID of WoW at character selection")
    parser.add_argument("--client-dir", type=Path, required=True)
    parser.add_argument("--relay-url", default="http://127.0.0.1:8765")
    parser.add_argument("--stormlib-module", type=Path, default=client_poc.DEFAULT_STORMLIB)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        client = args.client_dir.resolve()
        executable = duet_select.verified_executable(client)
        if (client / "SpotlightDuet.lab").read_text(encoding="ascii").strip() != duet_select.MARKER:
            raise ValueError("Use the isolated Spotlight observer marked with SpotlightDuet.lab.")
        runtime = duet_runtime.DuetRuntime(args.pid, client, args.stormlib_module.resolve())
        relay = Relay(args.relay_url)
        with exclusive_viewer(args.pid), runtime_poc.ClientProcess(args.pid, executable) as process:
            duet_select.verify_image(process)
            duet_select.install_once(process, args.pid, ())
            viewer = Viewer(process, runtime, relay, client / "Spotlight" / "shared")
            logging.info("Spotlight viewer is ready. Enter the world in WoW.")
            try:
                while True:
                    try:
                        viewer.tick()
                    except (OSError, ValueError) as error:
                        if process.read(duet_select.IMAGE_BASE, 2) != b"MZ":
                            break
                        logging.warning("Could not update Spotlight viewer: %s", error)
                    sleep(POLL_SECONDS)
            finally:
                if process.read(duet_select.IMAGE_BASE, 2) == b"MZ":
                    viewer.assignments.clear()
                    viewer.configure()
    except KeyboardInterrupt:
        return
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"Spotlight viewer failed: {error}\n")


if __name__ == "__main__":
    main()
