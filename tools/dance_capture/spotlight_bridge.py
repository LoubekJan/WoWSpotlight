"""Connect the Spotlight panel in an isolated WoW client to ComfyUI."""

import argparse
from collections import deque
import ctypes
from ctypes import wintypes
from hashlib import sha256
import logging
import os
from pathlib import Path
from queue import Empty, SimpleQueue
from shutil import copyfile
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic
import tkinter as tk
from tkinter import filedialog, messagebox

import client_poc
import duet_select
import runtime_poc
from spotlight_comfy import DEFAULT_COMFY_URL, run_comfy_video
from spotlight_http import Relay
from spotlight_ipc import (
    MAX_REPLY_BYTES, PAYLOAD_HEIGHT, PAYLOAD_SIGNALS, PAYLOAD_WIDTH, SIGNALS,
    color_index, error_reply, library_reply, read_payload,
)
from spotlight_library import DanceLibrary
from spotlight_publish import Publisher, local_dance, read_token


STATUS_KEYS = dict(selecting=0x74, uploading=0x75, processing=0x76, ready=0x77,
                   error=0x78, cancelled=0x79, receive=0x7A)


class KeyboardInput(ctypes.Structure):
    _fields_ = [("key", wintypes.WORD), ("scan", wintypes.WORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]


class MouseInput(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG), ("data", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]


class InputData(ctypes.Union):
    _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [("kind", wintypes.DWORD), ("data", InputData)]


class GameWindow:
    def __init__(self, executable):
        self.executable = executable
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.enum_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = (self.enum_callback, wintypes.LPARAM)
        self.user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.IsWindowVisible.argtypes = (wintypes.HWND,)
        self.user.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
        self.user.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        self.user.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        self.user.GetDC.argtypes = (wintypes.HWND,)
        self.user.GetDC.restype = wintypes.HDC
        self.user.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
        self.gdi.GetPixel.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
        self.gdi.GetPixel.restype = wintypes.DWORD
        self.gdi.CreateCompatibleDC.argtypes = (wintypes.HDC,)
        self.gdi.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
        self.gdi.CreateCompatibleBitmap.restype = wintypes.HANDLE
        self.gdi.SelectObject.argtypes = (wintypes.HDC, wintypes.HANDLE)
        self.gdi.SelectObject.restype = wintypes.HANDLE
        self.gdi.BitBlt.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD)
        self.gdi.BitBlt.restype = wintypes.BOOL
        self.gdi.DeleteDC.argtypes = (wintypes.HDC,)
        self.gdi.DeleteObject.argtypes = (wintypes.HANDLE,)
        self.user.SetForegroundWindow.argtypes = (wintypes.HWND,)
        self.user.keybd_event.argtypes = (wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t)
        self.user.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int)
        self.user.SendInput.restype = wintypes.UINT
        self.user.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
        )

    def locate(self, expected_pid=None):
        matches = []

        @self.enum_callback
        def visit(hwnd, _):
            if not self.user.IsWindowVisible(hwnd) or not self.user.GetWindowTextLengthW(hwnd):
                return True
            pid = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if expected_pid is not None and pid.value != expected_pid:
                return True
            handle = self.kernel.OpenProcess(0x1000, False, pid.value)
            if not handle:
                return True
            try:
                name = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(name))
                if self.kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
                    if Path(name.value) == self.executable:
                        matches.append((hwnd, pid.value))
            finally:
                self.kernel.CloseHandle(handle)
            return True

        self.user.EnumWindows(visit, 0)
        if len(matches) > 1:
            raise ValueError("Ze složky LiveActor nech spuštěné právě jedno okno WoW.")
        return next(iter(matches), None)

    def process_alive(self, pid):
        handle = self.kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return self.kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT
        finally:
            self.kernel.CloseHandle(handle)

    def can_input(self, hwnd):
        # Wait until the intended game window has focus and modifiers are released.
        return self.user.GetForegroundWindow() == hwnd and not any(
            self.user.GetAsyncKeyState(key) < 0 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C)
        )

    def notify(self, hwnd, status):
        if not self.can_input(hwnd):
            return False
        key = STATUS_KEYS[status]
        chord = (0x11, 0x10, key)  # Ctrl+Shift+F5..F11
        for button in chord:
            self.user.keybd_event(button, 0, 0, 0)
        for button in reversed(chord):
            self.user.keybd_event(button, 0, 2, 0)
        return True

    def send_reply(self, hwnd, reply):
        if not self.can_input(hwnd):
            return False
        payload = reply.encode("ascii")
        if len(payload) > MAX_REPLY_BYTES or any(not 32 <= byte < 127 for byte in payload):
            raise ValueError("Invalid Spotlight reply.")
        # The private edit box uses ordinary A–P keys so the old client need not
        # handle synthetic Unicode or layout-specific punctuation.
        keys = payload.hex().translate(str.maketrans("0123456789abcdef", "ABCDEFGHIJKLMNOP"))
        events = (Input * (len(keys) * 2))()
        for index, key in enumerate(keys):
            events[index * 2] = Input(1, InputData(keyboard=KeyboardInput(ord(key), 0, 0)))
            events[index * 2 + 1] = Input(1, InputData(keyboard=KeyboardInput(ord(key), 0, 2)))
        return self.user.SendInput(len(events), events, ctypes.sizeof(Input)) == len(events)

    def commit_reply(self, hwnd):
        if not self.can_input(hwnd):
            return False
        self.user.keybd_event(0x0D, 0, 0, 0)  # Return
        self.user.keybd_event(0x0D, 0, 2, 0)
        return True

    def is_current(self, hwnd, pid):
        current_pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(current_pid))
        return current_pid.value == pid

    def request_signal(self, hwnd, previous):
        if self.user.GetForegroundWindow() != hwnd:
            return None, None
        rect, origin = wintypes.RECT(), wintypes.POINT()
        if not self.user.GetClientRect(hwnd, ctypes.byref(rect)) or not self.user.ClientToScreen(hwnd, ctypes.byref(origin)):
            return None, None
        width, height = rect.right - rect.left, rect.bottom - rect.top
        dc = self.user.GetDC(None)
        if not dc:
            return None, None
        try:
            def sample(x, y):
                return color_index(self.gdi.GetPixel(dc, origin.x + round(width * x), origin.y + round(height * y)))

            signal = SIGNALS.get(tuple(sample(index / 100, 0.02) for index in range(1, 5)))
            if signal in PAYLOAD_SIGNALS and signal != previous:
                try:
                    return signal, self.capture_payload(hwnd, dc, origin, width, height, signal)
                except ValueError:
                    return None, None
            return signal, None
        finally:
            self.user.ReleaseDC(None, dc)

    def capture_payload(self, hwnd, dc, origin, width, height, signal):
        # One bounded screen copy keeps every symbol from the same frame and
        # avoids a separate desktop read for each payload pixel.
        columns, rows = round(width * PAYLOAD_WIDTH) + 1, round(height * PAYLOAD_HEIGHT) + 1
        memory = self.gdi.CreateCompatibleDC(dc)
        bitmap = self.gdi.CreateCompatibleBitmap(dc, columns, rows)
        previous = None
        try:
            if memory and bitmap:
                previous = self.gdi.SelectObject(memory, bitmap)
                if previous == ctypes.c_void_p(-1).value:
                    previous = None
            if (not previous or self.user.GetForegroundWindow() != hwnd
                    or not self.gdi.BitBlt(memory, 0, 0, columns, rows, dc, origin.x, origin.y, 0x00CC0020)):
                raise ValueError("Could not read the Spotlight payload.")

            def sample(x, y):
                return color_index(self.gdi.GetPixel(memory, round(width * x), round(height * y)))

            if SIGNALS.get(tuple(sample(index / 100, 0.02) for index in range(1, 5))) != signal:
                raise ValueError("Spotlight request changed before it could be read.")
            return read_payload(sample)
        finally:
            if previous:
                self.gdi.SelectObject(memory, previous)
            if bitmap:
                self.gdi.DeleteObject(bitmap)
            if memory:
                self.gdi.DeleteDC(memory)

    def lock(self, pid=None):
        name = sha256(str(self.executable).casefold().encode()).hexdigest()
        suffix = f"-{pid}" if pid is not None else ""
        mutex = self.kernel.CreateMutexW(None, False, f"Local\\WoWSpotlight-{name}{suffix}")
        error = ctypes.get_last_error()
        if not mutex:
            raise ctypes.WinError(error)
        if error == 183:  # ERROR_ALREADY_EXISTS
            self.kernel.CloseHandle(mutex)
            raise ValueError("Pomocná aplikace Spotlight už pro tento klient běží.")
        return mutex


class SpotlightBridge:
    def __init__(self, root, game, client_dir, base_url, stormlib_module, publisher, session=None, game_pid=None):
        self.root, self.game, self.client_dir, self.base_url = root, game, client_dir, base_url
        self.stormlib_module = stormlib_module
        self.events = SimpleQueue()
        self.busy = False
        self.status = None
        self.last_window = None
        self.signal_visible = None
        self.replies = deque()
        self.reply_started = None
        self.reply_attempts = 0
        self.reply_written = False
        self.character = 0
        self.loaded_clip = None
        self.retry_video = None
        self.page = 1
        self.publisher = publisher
        self.publisher_thread = None
        self.session = session
        self.session_thread = None
        self.game_pid = game_pid
        samples = client_dir.parent / "Clips"
        self.video_dir = samples if samples.is_dir() else Path.home()

    def player(self, pid, *, emote=False):
        with runtime_poc.ClientProcess(pid, self.game.executable, rights=duet_select.PROCESS_READ_RIGHTS) as process:
            return local_dance(process) if emote else duet_select.active_guid(process)

    def activate(self, pid, guid, library, clip_id):
        current, dancing = self.player(pid, emote=True)
        if current != guid:
            raise ValueError("The active character changed. Open Spotlight again on the intended character.")
        if dancing and self.publisher:
            raise ValueError("Move to stop the current dance before loading another one.")
        active = self.client_dir / "Spotlight" / "active.pose.json"
        with TemporaryDirectory(dir=active.parent) as work:
            motion = Path(work) / "active.pose.json"
            copyfile(library.path_for(clip_id), motion)
            shared_clip = self.publisher.relay.upload(motion) if self.publisher else None
            if self.player(pid) != guid:
                raise ValueError("The active character changed before the dance could be loaded.")
            if self.session:
                applied = self.session.load(guid, motion)
            else:
                applied = runtime_poc.apply(pid, self.client_dir, motion, self.stormlib_module)
            motion.replace(active)
        if self.publisher:
            self.publisher.prepare(guid, shared_clip)
        self.loaded_clip = (guid, clip_id)
        logging.info("Library dance %s ready: %s; shared=%s", clip_id, applied, shared_clip)

    def send_page(self, library, guid):
        loaded = self.loaded_clip[1] if self.loaded_clip and self.loaded_clip[0] == guid else None
        retryable = bool(self.retry_video and self.retry_video[0] == guid)
        self.events.put(("reply", guid, library_reply(library.entries(), self.page, loaded, retryable)))

    def work(self, action, payload, pid, guid):
        try:
            logging.info("Spotlight %s request for 0x%016X.", action, guid)
            if self.session and action in ("upload", "load", "retry"):
                self.session.require_ready()
            library = DanceLibrary(self.client_dir, guid)
            if action == "list":
                self.page = int(payload) if payload.isascii() and payload.isdecimal() else 1
            elif action == "rename":
                clip_id, name = payload.split("|", 1)
                library.rename(clip_id, name)
            elif action == "load":
                self.activate(pid, guid, library, payload)
                self.events.put(("status", guid, "ready"))
            else:
                video = payload if action == "upload" else (
                    self.retry_video[1] if self.retry_video and self.retry_video[0] == guid else None)
                if not video:
                    raise ValueError("Choose an MP4 to upload first.")
                self.retry_video = (guid, video)
                active = self.client_dir / "Spotlight"
                active.mkdir(parents=True, exist_ok=True)
                self.events.put(("status", guid, "uploading"))
                with TemporaryDirectory(dir=active) as work:
                    motion = Path(work) / "motion.json"
                    result = run_comfy_video(video, motion, base_url=self.base_url,
                                             on_status=lambda message: self.progress(guid, message))
                    entry = library.save(motion)
                self.retry_video = None
                self.page = 1
                logging.info("Saved library dance %s from ComfyUI prompt %s.", entry.clip_id, result["prompt_id"])
                self.activate(pid, guid, library, entry.clip_id)
                self.events.put(("status", guid, "ready"))
            self.send_page(library, guid)
        except Exception as error:
            logging.exception("Spotlight %s failed", action)
            retryable = bool(self.retry_video and self.retry_video[0] == guid)
            if action in ("upload", "load", "retry"):
                self.events.put(("status", guid, "error"))
            message = str(error).splitlines()[0] if str(error).strip() else "Spotlight could not finish this request."
            self.events.put(("reply", guid, error_reply(message, retryable)))
        finally:
            self.events.put(("done", guid, None))

    def progress(self, guid, message):
        logging.info("%s", message)
        if "zprac" in message.lower() or "front" in message.lower():
            self.events.put(("status", guid, "processing"))

    def choose(self, hwnd, pid, guid):
        self.busy = True
        if self.session:
            try:
                self.session.require_ready()
            except ValueError as error:
                self.events.put(("status", guid, "error"))
                self.events.put(("reply", guid, error_reply(str(error), False)))
                self.events.put(("done", guid, None))
                return
        try:
            logging.info("Opening Spotlight video picker")
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            video = filedialog.askopenfilename(
                parent=self.root, title="Spotlight – vyber taneční video", initialdir=str(self.video_dir),
                filetypes=[("Video MP4", "*.mp4")],
            )
        except tk.TclError:
            logging.exception("File picker failed")
            self.events.put(("status", guid, "error"))
            self.events.put(("done", guid, None))
            return
        finally:
            self.root.withdraw()
            self.game.user.SetForegroundWindow(hwnd)
        if not video:
            self.events.put(("status", guid, "cancelled"))
            self.events.put(("done", guid, None))
            return
        self.video_dir = Path(video).parent
        Thread(target=self.work, args=("upload", Path(video), pid, guid), daemon=True).start()

    def deliver_reply(self, hwnd, signal):
        if not self.replies or self.status:
            return
        if self.reply_started is None:
            if signal != "receive" and self.game.notify(hwnd, "receive"):
                self.reply_started = monotonic()
                self.reply_attempts += 1
        elif signal == "receive":
            if not self.reply_written:
                self.reply_written = self.game.send_reply(hwnd, self.replies[0])
            elif self.game.commit_reply(hwnd):
                self.replies.popleft()
                self.reply_started = None
                self.reply_attempts = 0
                self.reply_written = False
        elif monotonic() - self.reply_started >= 1.5:
            self.reply_started = None
            self.reply_written = False
            if self.reply_attempts >= 3:
                logging.warning("Spotlight add-on did not acknowledge a library reply.")
                self.replies.popleft()
                self.reply_attempts = 0

    def poll(self):
        try:
            window = self.last_window
            if window is None:
                if self.game_pid is not None and not self.game.process_alive(self.game_pid):
                    self.root.destroy()
                    return
                window = self.game.locate(self.game_pid)
            elif not self.game.is_current(*window):
                self.root.destroy()
                return
        except ValueError as error:
            messagebox.showerror("Spotlight", str(error), parent=self.root)
            self.root.destroy()
            return
        if window:
            self.last_window = window
            hwnd, pid = window
            if self.session and self.session_thread is None:
                self.session_thread = Thread(target=self.session.watch, args=(pid,), daemon=True)
                self.session_thread.start()
            if self.publisher and self.publisher_thread is None:
                self.publisher_thread = Thread(target=self.publisher.watch, args=(pid, self.game.executable), daemon=True)
                self.publisher_thread.start()
            try:
                guid = self.player(pid)
            except (OSError, ValueError):
                guid = 0
            if self.character != guid:
                self.character = guid
                self.loaded_clip = None
                self.status = None
                self.replies.clear()
                self.reply_started = None
                self.reply_attempts = 0
                self.reply_written = False
                self.page = 1
            while True:
                try:
                    kind, owner, value = self.events.get_nowait()
                except Empty:
                    break
                if kind == "done":
                    self.busy = False
                elif owner == guid:
                    if kind == "status":
                        self.status = value
                    else:
                        self.replies.append(value)
            signal, payload = self.game.request_signal(hwnd, self.signal_visible)
            new_signal = guid and signal != self.signal_visible
            if signal == "upload" and new_signal and not self.busy and self.status is None:
                self.busy = True
                self.status = "selecting"
                self.root.after(250, lambda: self.choose(hwnd, pid, guid))
            elif signal == "play" and new_signal and self.publisher and self.loaded_clip and self.loaded_clip[0] == guid:
                self.publisher.play()
            elif signal in PAYLOAD_SIGNALS and new_signal and not self.busy:
                self.busy = True
                Thread(target=self.work, args=(signal, payload, pid, guid), daemon=True).start()
            self.signal_visible = signal
            if self.status and self.game.notify(hwnd, self.status):
                self.status = None
            else:
                self.deliver_reply(hwnd, signal)
        self.root.after(250, self.poll)


def main(argv=None, *, session_factory=None, game_pid=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", type=Path, default=runtime_poc.DEFAULT_CLIENT)
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    parser.add_argument("--stormlib-module", type=Path, default=client_poc.DEFAULT_STORMLIB)
    parser.add_argument("--relay-url", help="Optional Spotlight relay for sharing dances")
    parser.add_argument("--relay-token-file", type=Path, help="Private token for this test character")
    parser.add_argument("--launch", action="store_true", help="Start the test client if its window is closed")
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("The Spotlight game companion requires Windows.")
    if bool(args.relay_url) != bool(args.relay_token_file):
        parser.error("Pass --relay-url and --relay-token-file together to share dances.")

    ctypes.WinDLL("user32").SetProcessDPIAware()
    root = tk.Tk()
    root.withdraw()
    root.title("Spotlight")
    root.geometry("360x86")
    tk.Label(root, text="Vyber taneční video ve formátu MP4.").pack(expand=True)
    root.attributes("-topmost", True)
    client_dir = args.client_dir.resolve()
    executable = client_dir / "WoW.exe"
    mutex = None
    publisher = None
    try:
        if client_dir == client_poc.DEFAULT_DATA.resolve().parent:
            raise ValueError("Použij oddělenou testovací kopii WoW.")
        if not runtime_poc.is_verified_executable(executable):
            raise ValueError("Spotlight potřebuje původní WoW 3.3.5a enUS (build 12340) nebo ověřenou variantu klienta.")
        if args.relay_url:
            publisher = Publisher(Relay(args.relay_url, read_token(args.relay_token_file)))
        logs = client_dir / "Logs"
        logs.mkdir(exist_ok=True)
        logging.basicConfig(filename=logs / "SpotlightBridge.log", encoding="utf-8", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
        game = GameWindow(executable)
        mutex = game.lock(game_pid)
        if game_pid is None and game.locate() is None:
            if not args.launch:
                raise ValueError("Spusť nejdřív WoW z testovací složky LiveActor.")
            subprocess.Popen([str(executable)], cwd=client_dir)
    except (OSError, ValueError) as error:
        if mutex:
            game.kernel.CloseHandle(mutex)
        messagebox.showerror("Spotlight", str(error), parent=root)
        root.destroy()
        return
    stormlib_module = args.stormlib_module.resolve()
    session = session_factory(client_dir, stormlib_module) if session_factory else None
    bridge = SpotlightBridge(root, game, client_dir, args.comfy_url, stormlib_module, publisher, session, game_pid)
    logging.info("Spotlight is waiting for requests from %s", executable)
    root.after(250, bridge.poll)
    try:
        root.mainloop()
    finally:
        if session:
            session.close()
            if bridge.session_thread:
                bridge.session_thread.join(timeout=4)
        if publisher:
            publisher.close()
            if bridge.publisher_thread:
                bridge.publisher_thread.join(timeout=4)
        game.kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
