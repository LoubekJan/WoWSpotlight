"""Build a login-screen preview for two locally installed dance slots."""

import argparse
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory

from client_poc import DEFAULT_DATA, DEFAULT_STORMLIB
from duet_assets import preview_login
from preview_poc import LOGIN_SCRIPT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New locale MPQ outside the client")
    parser.add_argument("--client-data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--stormlib-module", type=Path, default=DEFAULT_STORMLIB)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.suffix.lower() != ".mpq" or output.exists():
        parser.error("Use the path to a new .MPQ file.")
    if any(output.is_relative_to(path.resolve().parent) for path in (args.client_data, DEFAULT_DATA)):
        parser.error("Build the preview outside the client and install it only on a test copy.")

    try:
        spec = spec_from_file_location("spotlight_duet_preview_stormlib", args.stormlib_module)
        if spec is None or spec.loader is None:
            raise ImportError("Pass the path to the StormLib Python wrapper.")
        stormlib = module_from_spec(spec)
        spec.loader.exec_module(stormlib)
        payload = preview_login(stormlib.Archive, args.client_data)
        output.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=output.parent) as work:
            staged = Path(work) / output.name
            with stormlib.Archive(staged, create=True, capacity=8) as archive:
                archive.write(LOGIN_SCRIPT, payload)
            with stormlib.Archive(staged) as archive:
                if archive.read(LOGIN_SCRIPT) != payload:
                    raise ValueError("The preview patch could not be verified.")
            staged.rename(output)
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"Duet preview patch failed: {error}\n")
    print(output)


if __name__ == "__main__":
    main()
