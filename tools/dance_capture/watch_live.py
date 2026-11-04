"""Apply each new active pose JSON to one isolated running Spotlight client."""

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

if __package__:
    from . import runtime_poc
else:
    import runtime_poc


POLL_SECONDS = 0.25
RETRY_SECONDS = 1


def generation(path):
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def stage(active_path, snapshot, current):
    try:
        content = active_path.read_bytes()
    except (FileNotFoundError, PermissionError):
        return False
    if generation(active_path) != current:
        return False
    snapshot.write_bytes(content)
    return True


def watch(pid, client_dir, active_path, stormlib_module, snapshot):
    handled = None
    staged = None
    last_error = None
    retry_at = 0
    while True:
        current = generation(active_path)
        if current is not None and current != handled:
            if current != staged and stage(active_path, snapshot, current):
                staged = current
                last_error = None
                retry_at = 0
            if staged == current and time.monotonic() >= retry_at:
                try:
                    result = runtime_poc.apply(pid, client_dir, snapshot, stormlib_module)
                except runtime_poc.TrackNotReadyError as error:
                    message = str(error)
                    if message != last_error:
                        print(f"Waiting for the client animation: {message}", file=sys.stderr, flush=True)
                        last_error = message
                    retry_at = time.monotonic() + RETRY_SECONDS
                except runtime_poc.PoseClipError as error:
                    print(f"Keeping the current clip: {error}", file=sys.stderr, flush=True)
                    handled = current
                else:
                    print(json.dumps(result), flush=True)
                    handled = current
        time.sleep(POLL_SECONDS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int, help="PID of the running isolated WoW client")
    parser.add_argument("active_pose", type=Path, help="Path where new pose JSON is atomically published")
    parser.add_argument("--client-dir", type=Path, default=runtime_poc.DEFAULT_CLIENT)
    parser.add_argument("--stormlib-module", type=Path, default=runtime_poc.client_poc.DEFAULT_STORMLIB)
    args = parser.parse_args()
    if args.pid <= 0:
        parser.error("Pass a positive client PID.")

    try:
        with TemporaryDirectory(prefix="spotlight-watch-") as workspace:
            watch(args.pid, args.client_dir, args.active_pose.absolute(), args.stormlib_module,
                  Path(workspace) / "active.pose.json")
    except KeyboardInterrupt:
        return
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"Live dance watcher failed: {error}\n")


if __name__ == "__main__":
    main()
