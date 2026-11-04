"""Coordinate local and shared animation slots in the same WoW client."""

import logging
from threading import Event, Lock

import client_poc
import duet_runtime
import duet_select
import runtime_poc
from spotlight_viewer import POLL_SECONDS, Viewer


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

    def close(self):
        self.closed.set()

    def watch(self, pid):
        try:
            runtime = duet_runtime.DuetRuntime(pid, self.client_dir, self.stormlib_module)
            remote_slots = tuple(slot for slot in runtime.slots if slot != client_poc.ANIMATION_ID)
            if len(remote_slots) != 2:
                raise ValueError("Install the unified Spotlight Data\\patch-Z.MPQ with all three animation slots.")
            with runtime_poc.ClientProcess(pid, runtime.executable) as process:
                duet_select.verify_image(process)
                duet_select.install_once(process, pid)
                self.viewer = Viewer(process, runtime, self.relay, self.client_dir / "Spotlight" / "shared",
                                     slots=remote_slots)
                self.ready.set()
                logging.info("Spotlight local and shared animation slots are ready.")
                try:
                    while not self.closed.is_set() and process.read(duet_select.IMAGE_BASE, 2) == b"MZ":
                        with self.lock:
                            try:
                                if duet_select.active_guid(process) != self.viewer.local_guid:
                                    self.viewer.local_guid = 0
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

    def load(self, guid, motion):
        if not self.ready.wait(5):
            raise ValueError("Spotlight is still preparing the client. Try again in a moment.")
        with self.lock:
            viewer = self.viewer
            if not viewer:
                raise ValueError(str(self.error or "Spotlight could not attach to the client."))
            if duet_select.active_guid(viewer.process) != guid:
                raise ValueError("The active character changed before the dance could be loaded.")
            report = viewer.runtime.apply(client_poc.ANIMATION_ID, motion)
            if duet_select.active_guid(viewer.process) != guid:
                raise ValueError("The active character changed before the dance could be selected.")
            viewer.local_guid = guid
            viewer.configure()
            return report
