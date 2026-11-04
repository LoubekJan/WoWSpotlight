"""Replace one verified duet animation slot in a running isolated WoW client."""

import argparse
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

if __package__:
    from . import client_poc, duet_assets, duet_multirig, duet_select, runtime_poc, spotlight_rigs
else:
    import client_poc
    import duet_assets
    import duet_multirig
    import duet_select
    import runtime_poc
    import spotlight_rigs


LEGACY_RIG = "HumanMale"


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
        self.data = self.client_dir / "Data"
        self.patch = self.data / "patch-Z.MPQ"
        if not self.patch.is_file():
            raise FileNotFoundError("Chybí Data\\patch-Z.MPQ. Po doplnění restartuj WoW.")

        spec = spec_from_file_location("spotlight_duet_stormlib", stormlib_module)
        if spec is None or spec.loader is None:
            raise ImportError("Pass the path to the StormLib Python wrapper.")
        stormlib = module_from_spec(spec)
        spec.loader.exec_module(stormlib)
        self.archive_type = stormlib.Archive
        self.rig_cache = {}
        with self.archive_type(self.patch) as archive:
            self.multirig = duet_multirig.is_multirig(archive)
        if self.multirig:
            self.local_slot = duet_multirig.LOCAL_SLOT
            self.slots = duet_multirig.SLOTS
            self.rigs = frozenset(spotlight_rigs.PLAYABLE_MODELS)
            self.model = duet_multirig.read_model(self.archive_type, self.data, LEGACY_RIG)
            return

        self.local_slot = client_poc.ANIMATION_ID
        self.rigs = frozenset({LEGACY_RIG})
        self.model = client_poc.read_source(stormlib.Archive, self.data / "patch-3.MPQ",
                                            client_poc.MODEL_PATH, client_poc.MODEL_HASH)
        self.stock = client_poc.read_source(stormlib.Archive, self.data / "patch-2.MPQ",
                                            client_poc.ANIMATION_PATH, client_poc.ANIMATION_HASH)
        self.tracks = client_poc.full_body_tracks(self.model, self.stock)
        self.translations = client_poc.translation_ranges(self.model)
        with self.archive_type(self.patch) as archive:
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

    def rig(self, name):
        if name not in self.rig_cache:
            source = self.model if name == LEGACY_RIG else duet_multirig.read_model(self.archive_type, self.data, name)
            with self.archive_type(self.patch) as archive:
                self.rig_cache[name] = duet_multirig.load_rig(archive, name, source)
        return self.rig_cache[name]

    def apply(self, slot, clip_path, *, rig=LEGACY_RIG):
        if slot not in self.slots:
            raise ValueError("Choose one of the verified duet animation slots.")
        if rig not in self.rigs:
            raise ValueError("Use a supported player character in its normal form.")
        try:
            clip = json.loads(Path(clip_path).read_text(encoding="utf-8"))
            if clip.get("format") != client_poc.FULL_BODY_FORMAT:
                raise ValueError("Expected Spotlight full-body motion.")
            if self.multirig:
                assets = self.rig(rig)
                stock, tracks, translations = assets.stock, assets.tracks, assets.translations
                duration_ms = next(iter(tracks.values())).timestamps[-1]
                times, rotations = client_poc.full_body_motion(clip, duration_ms)
                rotations = spotlight_rigs.retarget_rotations(self.model, assets.model, rig, rotations)
                target, stats = client_poc.bake_rotations(stock, tracks, translations, times, rotations, duration_ms,
                                                          loop=clip.get("loop", False))
                footer = duet_multirig.slot_footer(rig, slot)
            else:
                stock, tracks, translations = self.stock, self.tracks, self.translations
                target, stats = client_poc.bake_clip(self.model, stock, clip)
                footer = duet_assets.slot_footer(slot)
        except (AttributeError, IndexError, KeyError, OverflowError, TypeError, ValueError) as error:
            raise runtime_poc.PoseClipError(str(error)) from error

        with runtime_poc.ClientProcess(self.pid, self.executable) as process:
            result = runtime_poc.replace_animation(process, stock + footer, target + footer,
                                                   tracks, translations, anchor_offset=len(stock))
        result["animation_sha256"] = sha256(target).hexdigest()
        return {"pid": self.pid, "animation": slot, "rig": rig, **stats, **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int, help="PID of the isolated duet WoW.exe")
    parser.add_argument("clip", type=Path, help="Spotlight full-body motion JSON")
    parser.add_argument("--slot", type=int, choices=sorted(set(duet_assets.UNIFIED_SLOT_MEMBERS) | set(duet_multirig.SLOTS)),
                        required=True)
    parser.add_argument("--rig", choices=spotlight_rigs.PLAYABLE_MODELS, default=LEGACY_RIG)
    parser.add_argument("--client-dir", type=Path, required=True)
    parser.add_argument("--stormlib-module", type=Path, default=client_poc.DEFAULT_STORMLIB)
    args = parser.parse_args()
    try:
        runtime = DuetRuntime(args.pid, args.client_dir, args.stormlib_module)
        result = runtime.apply(args.slot, args.clip, rig=args.rig)
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"Duet live update failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
