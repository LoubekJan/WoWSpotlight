"""Coordinate local and shared animation slots in the same WoW client."""

import logging
from queue import Empty, SimpleQueue
from threading import Event, Lock
from time import monotonic

import client_poc
import duet_runtime
import duet_select
import runtime_poc
from spotlight_viewer import NATIVE_DANCE, POLL_SECONDS, STOCK_DANCE_ANIMATION, Viewer


class SpotlightSession:
    def __init__(self, client_dir, stormlib_module, relay):
        self.client_dir = client_dir
        self.stormlib_module = stormlib_module
        self.relay = relay
        self.lock = Lock()
        self.ready = Event()
        self.closed = Event()
        self.viewer = None
        self.error = None
        self.playback = SimpleQueue()

    def close(self):
        self.closed.set()

    def request_playback(self, guid, custom, notify=None):
        self.playback.put((guid, custom, monotonic() + 5, notify))

    def switch_dance(self, viewer, guid, custom, on_play):
        process = viewer.process
        if duet_select.active_guid(process) != guid:
            return True
        previous = viewer.local_guid
        if not custom:
            viewer.local_guid = 0
            viewer.configure()
        manager = duet_select.object_manager(process)
        snapshot = duet_select.actor_snapshot(process, manager, guid)
        if snapshot.get("emote_state") != NATIVE_DANCE or snapshot.get("stand_state") != 0:
            return not custom
        if not custom and snapshot.get("active_animation") != client_poc.ANIMATION_ID:
            return True

        slot = client_poc.ANIMATION_ID if custom else STOCK_DANCE_ANIMATION
        switched = False
        try:
            if custom:
                viewer.local_guid = guid
                viewer.configure()
            switched = duet_select.sync_actor(process, manager, guid, slot, 0)
        finally:
            if custom and not switched:
                viewer.local_guid = previous
                viewer.configure()
        if switched:
            logging.info("Local dance for 0x%016X selected animation %d.", guid, slot)
            if on_play:
                on_play()
        return switched

    def release_local_dance(self, viewer):
        guid = viewer.local_guid
        if not guid:
            return
        process = viewer.process
        if duet_select.active_guid(process) == guid:
            snapshot = duet_select.actor_snapshot(process, duet_select.object_manager(process), guid)
            emote = snapshot.get("emote_state")
            if emote is None or emote == NATIVE_DANCE and snapshot.get("stand_state") == 0:
                return
        viewer.local_guid = 0
        viewer.configure()

    def watch(self, pid):
        try:
            runtime = duet_runtime.DuetRuntime(pid, self.client_dir, self.stormlib_module)
            remote_slots = tuple(slot for slot in runtime.slots if slot != client_poc.ANIMATION_ID)
            if len(remote_slots) != 2:
                raise ValueError("Install the unified Spotlight Data\\patch-Z.MPQ with all three animation slots.")
            with runtime_poc.ClientProcess(pid, runtime.executable) as process:
                duet_select.verify_image(process)
                while not self.closed.is_set() and process.read(duet_select.IMAGE_BASE, 2) == b"MZ":
                    try:
                        duet_select.install_once(process, pid)
                    except ValueError:
                        if not duet_select.active_guid(process) or duet_select.inspect_selector(process) is not None:
                            raise
                        self.closed.wait(POLL_SECONDS)
                    else:
                        break
                else:
                    return
                self.viewer = Viewer(process, runtime, self.relay, self.client_dir / "Spotlight" / "shared",
                                     slots=remote_slots)
                self.ready.set()
                logging.info("Spotlight local and shared animation slots are ready.")
                pending = None
                try:
                    while not self.closed.is_set() and process.read(duet_select.IMAGE_BASE, 2) == b"MZ":
                        with self.lock:
                            try:
                                self.release_local_dance(self.viewer)
                                while True:
                                    try:
                                        pending = self.playback.get_nowait()
                                    except Empty:
                                        break
                                    if not pending[1] and pending[3]:
                                        pending[3]()  # End sharing in the same queue order as custom playback.
                                if pending:
                                    guid, custom, deadline, notify = pending
                                    if monotonic() >= deadline or self.switch_dance(
                                            self.viewer, guid, custom, notify if custom else None):
                                        pending = None
                                self.viewer.tick()
                            except (OSError, ValueError) as error:
                                logging.warning("Could not update Spotlight session: %s", error)
                        self.closed.wait(POLL_SECONDS)
                finally:
                    with self.lock:
                        self.viewer = None
        except (ImportError, OSError, ValueError) as error:
            self.error = error
            logging.exception("Could not start unified Spotlight animation playback.")
        finally:
            self.ready.set()

    def require_ready(self):
        if not self.ready.is_set():
            raise ValueError("Spotlight is still preparing the client. Try again in a moment.")
        if self.viewer is None:
            raise ValueError(str(self.error or "Spotlight could not attach to the client."))
        return self.viewer

    def load(self, guid, motion):
        self.ready.wait(5)
        with self.lock:
            viewer = self.require_ready()
            if duet_select.active_guid(viewer.process) != guid:
                raise ValueError("The active character changed before the dance could be loaded.")
            manager = duet_select.object_manager(viewer.process)
            snapshot = duet_select.actor_snapshot(viewer.process, manager, guid)
            if viewer.local_guid == guid or snapshot.get("active_animation") == client_poc.ANIMATION_ID:
                raise ValueError("Stop the current Spotlight dance before loading another one.")
            report = viewer.runtime.apply(client_poc.ANIMATION_ID, motion)
            if duet_select.active_guid(viewer.process) != guid:
                raise ValueError("The active character changed before the dance could be selected.")
            return report
