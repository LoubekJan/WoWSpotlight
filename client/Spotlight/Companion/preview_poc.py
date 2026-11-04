"""Build an offline login-screen preview for an isolated WoW 3.3.5a client."""

import argparse
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

if __package__:
    from .client_poc import DEFAULT_DATA, DEFAULT_STORMLIB
else:
    from client_poc import DEFAULT_DATA, DEFAULT_STORMLIB


LOGIN_SCRIPT = r"Interface\GlueXML\AccountLogin.lua"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New MPQ outside the client")
    parser.add_argument("--client-data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--stormlib-module", type=Path, default=DEFAULT_STORMLIB)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.suffix.lower() != ".mpq" or output.exists():
        parser.error("Use the path to a new .MPQ file.")
    if any(output.is_relative_to(path.resolve().parent) for path in (args.client_data, DEFAULT_DATA)):
        parser.error("Build the preview outside the client and install it only on a test copy.")

    try:
        spec = spec_from_file_location("dance_preview_stormlib", args.stormlib_module)
        if spec is None or spec.loader is None:
            raise ImportError("Pass the path to the StormLib Python wrapper.")
        stormlib = module_from_spec(spec)
        spec.loader.exec_module(stormlib)
        with stormlib.Archive(args.client_data / "enUS" / "patch-enUS-3.MPQ") as archive:
            login = archive.read(LOGIN_SCRIPT)
        preview = Path(__file__).with_name("preview.lua").read_bytes()
        with stormlib.Archive(output, create=True, capacity=8) as archive:
            archive.write(LOGIN_SCRIPT, login + b"\r\n" + preview)
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"Preview patch failed: {error}\n")
    print(output)


if __name__ == "__main__":
    main()
