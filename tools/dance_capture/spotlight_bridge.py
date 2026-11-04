"""Connect the Spotlight panel in an isolated WoW client to ComfyUI."""

import argparse
import ctypes
from ctypes import wintypes
from hashlib import sha256
import logging
import os
from pathlib import Path
from queue import Empty, SimpleQueue
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox

import client_poc
import runtime_poc
from spotlight_comfy import DEFAULT_COMFY_URL, run_comfy_video


STATUS_KEYS = dict(selecting=0x74, uploading=0x75, processing=0x76, ready=0x77,
                   error=0x78, cancelled=0x79)
SIGNAL_COLORS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 255))


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
        self.user.SetForegroundWindow.argtypes = (wintypes.HWND,)
        self.user.keybd_event.argtypes = (wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t)
        self.user.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
        )

    def locate(self):
        matches = []

        @self.enum_callback
        def visit(hwnd, _):
            if not self.user.IsWindowVisible(hwnd) or not self.user.GetWindowTextLengthW(hwnd):
                return True
            pid = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
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

    def notify(self, hwnd, status):
        # Wait until the intended game window has focus and modifiers are released.
        if self.user.GetForegroundWindow() != hwnd or any(
            self.user.GetAsyncKeyState(key) < 0 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C)
        ):
            return False
        key = STATUS_KEYS[status]
        chord = (0x11, 0x10, key)  # Ctrl+Shift+F5..F10
        for button in chord:
            self.user.keybd_event(button, 0, 0, 0)
        for button in reversed(chord):
            self.user.keybd_event(button, 0, 2, 0)
        return True

    def is_current(self, hwnd, pid):
        current_pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(current_pid))
        return current_pid.value == pid

    def upload_requested(self, hwnd):
        if self.user.GetForegroundWindow() != hwnd:
            return False
        rect, origin = wintypes.RECT(), wintypes.POINT()
        if not self.user.GetClientRect(hwnd, ctypes.byref(rect)) or not self.user.ClientToScreen(hwnd, ctypes.byref(origin)):
            return False
        width, height = rect.right - rect.left, rect.bottom - rect.top
        dc = self.user.GetDC(None)
        if not dc:
            return False
        try:
            # Read only the four marker pixels in the intended foreground client.
            y = origin.y + round(height * 0.02)
            for index, expected in enumerate(SIGNAL_COLORS, 1):
                x = origin.x + round(width * index / 100)
                pixel = self.gdi.GetPixel(dc, x, y)
                actual = tuple((pixel >> shift) & 255 for shift in (0, 8, 16))
                if any(abs(a - e) > 45 for a, e in zip(actual, expected)):
                    return False
            return True
        finally:
            self.user.ReleaseDC(None, dc)

    def lock(self):
        name = sha256(str(self.executable).casefold().encode()).hexdigest()
        mutex = self.kernel.CreateMutexW(None, False, f"Local\\WoWSpotlight-{name}")
        error = ctypes.get_last_error()
        if not mutex:
            raise ctypes.WinError(error)
        if error == 183:  # ERROR_ALREADY_EXISTS
            self.kernel.CloseHandle(mutex)
            raise ValueError("Pomocná aplikace Spotlight už pro tento klient běží.")
        return mutex


class SpotlightBridge:
    def __init__(self, root, game, client_dir, base_url, stormlib_module):
        self.root, self.game, self.client_dir, self.base_url = root, game, client_dir, base_url
        self.stormlib_module = stormlib_module
        self.events = SimpleQueue()
        self.busy = False
        self.status = None
        self.last_window = None
        self.signal_visible = False
        samples = client_dir.parent / "Clips"
        self.video_dir = samples if samples.is_dir() else Path.home()

    def run(self, video, pid):
        try:
            active = self.client_dir / "Spotlight" / "active.pose.json"
            active.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=active.parent) as work:
                motion = Path(work) / "active.pose.json"
                result = run_comfy_video(video, motion, base_url=self.base_url, on_status=self.progress)
                applied = runtime_poc.apply(pid, self.client_dir, motion, self.stormlib_module)
                motion.replace(active)
            result["active_path"] = str(active)
            logging.info("Motion ready: %s; %s", result, applied)
        except Exception:
            logging.exception("Spotlight processing failed")
            self.events.put("error")
        else:
            self.events.put("ready")

    def progress(self, message):
        logging.info("%s", message)
        if "zprac" in message.lower() or "front" in message.lower():
            self.events.put("processing")

    def choose(self, hwnd, pid):
        self.busy = True
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
            self.events.put("error")
            return
        finally:
            self.root.withdraw()
            self.game.user.SetForegroundWindow(hwnd)
        if not video:
            self.events.put("cancelled")
            return
        self.video_dir = Path(video).parent
        self.status = "uploading"
        Thread(target=self.run, args=(Path(video), pid), daemon=True).start()

    def poll(self):
        try:
            window = self.last_window
            if window is None:
                window = self.game.locate()
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
            while True:
                try:
                    status = self.events.get_nowait()
                except Empty:
                    break
                self.status = status
                if status in ("ready", "error", "cancelled"):
                    self.busy = False
            signal = self.game.upload_requested(hwnd)
            if signal and not self.signal_visible and not self.busy and self.status is None:
                self.busy = True
                self.status = "selecting"
                self.root.after(250, lambda: self.choose(hwnd, pid))
            self.signal_visible = signal
            if self.status and self.game.notify(hwnd, self.status):
                self.status = None
        self.root.after(250, self.poll)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", type=Path, default=runtime_poc.DEFAULT_CLIENT)
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    parser.add_argument("--stormlib-module", type=Path, default=client_poc.DEFAULT_STORMLIB)
    parser.add_argument("--launch", action="store_true", help="Start the test client if its window is closed")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("The Spotlight game companion requires Windows.")

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
    try:
        if client_dir == client_poc.DEFAULT_DATA.resolve().parent:
            raise ValueError("Použij oddělenou testovací kopii WoW.")
        if sha256(executable.read_bytes()).hexdigest() != runtime_poc.CLIENT_HASH:
            raise ValueError("Tato kopie WoW neodpovídá ověřenému buildu 12340.")
        logs = client_dir / "Logs"
        logs.mkdir(exist_ok=True)
        logging.basicConfig(filename=logs / "SpotlightBridge.log", encoding="utf-8", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
        game = GameWindow(executable)
        mutex = game.lock()
        if game.locate() is None:
            if not args.launch:
                raise ValueError("Spusť nejdřív WoW z testovací složky LiveActor.")
            subprocess.Popen([str(executable)], cwd=client_dir)
    except (OSError, ValueError) as error:
        if mutex:
            game.kernel.CloseHandle(mutex)
        messagebox.showerror("Spotlight", str(error), parent=root)
        root.destroy()
        return
    bridge = SpotlightBridge(root, game, client_dir, args.comfy_url, args.stormlib_module.resolve())
    logging.info("Spotlight is waiting for requests from %s", executable)
    root.after(250, bridge.poll)
    try:
        root.mainloop()
    finally:
        game.kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
