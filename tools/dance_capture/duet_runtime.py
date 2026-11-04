"""Replace one verified duet animation slot in a running isolated WoW client."""

import argparse
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

if __package__:
    from . import client_poc, duet_assets, duet_select, runtime_poc
else:
    import client_poc
    import duet_assets
    import duet_select
    import runtime_poc


class DuetRuntime:
    def __init__(self, pid, client_dir, stormlib_module=client_poc.DEFAULT_STORMLIB):
        self.pid = pid
        self.client_dir = Path(client_dir).resolve()
        if self.client_dir == client_poc.DEFAULT_DATA.resolve().parent:
            raise ValueError("Select the isolated duet client copy.")
        if (self.client_dir / "SpotlightDuet.lab").read_text(encoding="ascii").strip() != duet_select.MARKER:
            raise ValueError("The selected client is missing the duet lab marker.")
        self.executable = self.client_dir / "WoW.exe"
        if not runtime_poc.is_verified_executable(self.executable):
            raise ValueError("The executable does not match a verified WoW 3.3.5a build 12340.")

        spec = spec_from_file_location("spotlight_duet_stormlib", stormlib_module)
        if spec is None or spec.loader is None:
            raise ImportError("Pass the path to the StormLib Python wrapper.")
        stormlib = module_from_spec(spec)
        spec.loader.exec_module(stormlib)
        data = self.client_dir / "Data"
        self.model = client_poc.read_source(stormlib.Archive, data / "patch-3.MPQ",
                                            client_poc.MODEL_PATH, client_poc.MODEL_HASH)
        self.stock = client_poc.read_source(stormlib.Archive, data / "patch-2.MPQ",
                                            client_poc.ANIMATION_PATH, client_poc.ANIMATION_HASH)
        self.tracks = client_poc.full_body_tracks(self.model, self.stock)
        self.translations = client_poc.translation_ranges(self.model)
        with stormlib.Archive(data / "patch-Z.MPQ") as archive:
            installed_model = archive.read(client_poc.MODEL_PATH)
            if installed_model == duet_assets.duplicate_slot(self.model):
                slot_members = duet_assets.SLOT_MEMBERS
            elif installed_model == duet_assets.duplicate_slot(self.model, third=True):
                slot_members = duet_assets.UNIFIED_SLOT_MEMBERS
            else:
                raise ValueError("The installed MPQ does not contain the verified duet model.")
            for slot, member in slot_members.items():
                animation = archive.read(member)
                if animation[len(self.stock):] != duet_assets.slot_footer(slot):
                    raise ValueError("Rebuild and install the duet MPQ with slot identifiers.")
        self.slots = tuple(slot_members)

    def apply(self, slot, clip_path):
        if slot not in self.slots:
            raise ValueError("Choose one of the verified duet animation slots.")
        try:
            clip = json.loads(Path(clip_path).read_text(encoding="utf-8"))
            if clip.get("format") != client_poc.FULL_BODY_FORMAT:
                raise ValueError("Expected Spotlight full-body motion.")
            target, stats = client_poc.bake_clip(self.model, self.stock, clip)
        except (AttributeError, IndexError, KeyError, OverflowError, TypeError, ValueError) as error:
            raise runtime_poc.PoseClipError(str(error)) from error

        footer = duet_assets.slot_footer(slot)
        with runtime_poc.ClientProcess(self.pid, self.executable) as process:
            result = runtime_poc.replace_animation(process, self.stock + footer, target + footer,
                                                   self.tracks, self.translations, anchor_offset=len(self.stock))
        result["animation_sha256"] = sha256(target).hexdigest()
        return {"pid": self.pid, "animation": slot, **stats, **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int, help="PID of the isolated duet WoW.exe")
    parser.add_argument("clip", type=Path, help="Spotlight full-body motion JSON")
    parser.add_argument("--slot", type=int, choices=duet_assets.UNIFIED_SLOT_MEMBERS, required=True)
    parser.add_argument("--client-dir", type=Path, required=True)
    parser.add_argument("--stormlib-module", type=Path, default=client_poc.DEFAULT_STORMLIB)
    args = parser.parse_args()
    try:
        runtime = DuetRuntime(args.pid, args.client_dir, args.stormlib_module)
        result = runtime.apply(args.slot, args.clip)
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"Duet live update failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
