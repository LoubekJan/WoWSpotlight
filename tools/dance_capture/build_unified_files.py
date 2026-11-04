"""Build the files to copy into one clean Spotlight WoW client."""

import argparse
import json
from pathlib import Path
from shutil import copy2, copytree, ignore_patterns
import struct
import sys
from tempfile import TemporaryDirectory

import client_poc
import duet_multirig
from stormlib import Archive, DLL_PATH


TOOLS = Path(__file__).resolve().parent
COMPANION = (
    "arm_motion", "client_poc", "duet_assets", "duet_multirig", "duet_runtime", "duet_select", "preview_poc", "runtime_poc",
    "spotlight_bridge", "spotlight_client", "spotlight_comfy", "spotlight_gallery", "spotlight_http", "spotlight_ipc",
    "spotlight_library", "spotlight_publish", "spotlight_rigs", "spotlight_session", "spotlight_viewer", "stormlib",
)


def copy_runtime(destination):
    source = Path(sys.base_prefix)
    destination.mkdir()
    for name in ("pythonw.exe", "python312.dll", "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
        copy2(source / name, destination / name)
    exclude = ignore_patterns("__pycache__", "site-packages", "test", "tests", "ensurepip", "idlelib")
    for name in ("DLLs", "Lib", "tcl"):
        copytree(source / name, destination / name, ignore=exclude)
    (destination / "python312._pth").write_text("Lib\nDLLs\n.\n", encoding="ascii")


def build_files(client_data, bootstrap, output, settings, realmlist):
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent, prefix="spotlight-files-") as work:
        work = Path(work)
        files = work / "client-files"
        app = files / "Spotlight" / "Companion"
        (app / "vendor").mkdir(parents=True)
        for name in COMPANION:
            copy2(TOOLS / f"{name}.py", app)
        copy2(DLL_PATH, app / "vendor")
        copy2(TOOLS / "StormLib-LICENSE.txt", app / "vendor")
        copy_runtime(app.parent / "Runtime")
        (app.parent / "settings.json").write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        copy2(bootstrap, files / "dinput8.dll")
        (files / "SpotlightDuet.lab").write_text("WoWSpotlight duet lab\n", encoding="ascii")

        addon = "SpotlightDanceLab"
        addon_source = TOOLS / "live_lab" / addon
        addon_destination = files / "Interface" / "AddOns" / addon
        addon_destination.mkdir(parents=True)
        copy2(addon_source / f"{addon}.lua", addon_destination)
        toc = (addon_source / f"{addon}.toc").read_text(encoding="utf-8")
        metadata = "## X-Spotlight-Unified: 1\n## X-Spotlight-MultiRig: 1\n"
        (addon_destination / f"{addon}.toc").write_text(metadata + toc, encoding="utf-8")
        duet_multirig.build_multirig(Archive, client_data, files / "Data" / "patch-Z.MPQ")
        realm_file = files / "Data" / "enUS" / "realmlist.wtf"
        realm_file.parent.mkdir()
        realm_file.write_text(f"set realmlist {realmlist}\n", encoding="ascii")
        files.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--client-data", type=Path, required=True)
    parser.add_argument("--bootstrap", type=Path, required=True)
    parser.add_argument("--comfy-url", default="http://192.168.0.248:8188")
    parser.add_argument("--gallery-url", default="http://192.168.0.248:9093")
    parser.add_argument("--relay-url", default="http://192.168.0.248:8765")
    parser.add_argument("--relay-realm-auth", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--realmlist", default="192.168.0.248")
    args = parser.parse_args()
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        parser.error("Use 64-bit Python 3.12 for Windows with Tcl/Tk.")
    output = args.output.resolve()
    data = args.client_data.resolve()
    if output.exists() or any(output.is_relative_to(path) for path in (data.parent, client_poc.DEFAULT_DATA.parent)):
        parser.error("Choose a new output folder outside the WoW client.")
    if not args.realmlist or not all(char.isascii() and (char.isalnum() or char in ".-:[]") for char in args.realmlist):
        parser.error("Supply a realm address without spaces.")
    try:
        settings = {"comfy_url": args.comfy_url, "gallery_url": args.gallery_url, "relay_url": args.relay_url,
                    "relay_realm_auth": args.relay_realm_auth}
        build_files(data, args.bootstrap, output, settings, args.realmlist)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Could not build Spotlight client files: {error}\n")
    print(output)


if __name__ == "__main__":
    main()
