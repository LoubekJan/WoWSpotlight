"""Save a downloadable WoW motion clip to the ComfyUI output directory."""

import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from uuid import uuid4


class SpotlightSaveMotion:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "motion": ("SPOTLIGHT_MOTION",),
                "name": ("STRING", {"default": "spotlight-dance"}),
            }
        }

    CATEGORY = "Spotlight/WoW"
    FUNCTION = "save"
    OUTPUT_NODE = True
    RETURN_TYPES = ()

    def save(self, motion, name):
        import folder_paths

        if motion.get("format") != "wow-spotlight-motion" or motion.get("version") != 1:
            raise ValueError("Expected a Spotlight motion clip, version 1.")
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-_-")[:64] or "spotlight-dance"
        filename = f"{name}-{uuid4().hex[:12]}.motion.json"
        subfolder = "spotlight"
        folder = Path(folder_paths.get_output_directory()) / subfolder
        folder.mkdir(parents=True, exist_ok=True)

        staged = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, delete=False) as stream:
                staged = Path(stream.name)
                json.dump(motion, stream, separators=(",", ":"), allow_nan=False)
                stream.write("\n")
            staged.replace(folder / filename)
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

        return {"ui": {"spotlight_files": [{"filename": filename, "subfolder": subfolder, "type": "output"}]}}
