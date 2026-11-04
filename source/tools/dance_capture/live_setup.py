"""Build the one-time client setup for the multiplayer Spotlight lab."""

import argparse
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import struct

from client_poc import ANIMATION_ID, DEFAULT_DATA, DEFAULT_STORMLIB


EMOTES = r"DBFilesClient\Emotes.dbc"
EMOTES_HASH = "f76e66c57bd355870a315d116dfa83304f1b7d21636fd1ca6cbf65e1f012e4cc"


def remap_dance(data):
    if sha256(data).hexdigest() != EMOTES_HASH:
        raise ValueError("Use the verified 3.3.5a enUS lab Emotes.dbc.")
    _, row_count, _, row_size, _ = struct.unpack_from("<4s4I", data)
    output = bytearray(data)
    for index in range(row_count):
        offset = 20 + index * row_size
        emote_id, _, animation_id = struct.unpack_from("<3I", data, offset)
        if emote_id == 10 and animation_id == 69:
            struct.pack_into("<I", output, offset + 8, ANIMATION_ID)
            return bytes(output)
    raise ValueError("The standard dance row was not found.")


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
        parser.error("Build the patch outside the client and install it only on a test copy.")

    try:
        spec = spec_from_file_location("dance_lab_stormlib", args.stormlib_module)
        if spec is None or spec.loader is None:
            raise ImportError("Pass the path to the StormLib Python wrapper.")
        stormlib = module_from_spec(spec)
        spec.loader.exec_module(stormlib)
        with stormlib.Archive(args.client_data / "enUS" / "patch-enUS-2.MPQ") as archive:
            emotes = remap_dance(archive.read(EMOTES))
        with stormlib.Archive(output, create=True, capacity=8) as archive:
            archive.write(EMOTES, emotes)
        with stormlib.Archive(output) as archive:
            if archive.read(EMOTES) != emotes:
                raise ValueError("The written dance mapping could not be verified.")
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"Live lab setup failed: {error}\n")
    print(output)


if __name__ == "__main__":
    main()
