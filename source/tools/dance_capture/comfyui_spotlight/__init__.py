"""ComfyUI nodes for the WoW Spotlight motion capture prototype."""

from .capture import SpotlightCapturePose
from .retarget import SpotlightRetargetHumanMale
from .save import SpotlightSaveMotion


NODE_CLASS_MAPPINGS = {
    "SpotlightCapturePose": SpotlightCapturePose,
    "SpotlightRetargetHumanMale": SpotlightRetargetHumanMale,
    "SpotlightSaveMotion": SpotlightSaveMotion,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SpotlightCapturePose": "Spotlight · Capture Body Pose",
    "SpotlightRetargetHumanMale": "Spotlight · Retarget to Human Male",
    "SpotlightSaveMotion": "Spotlight · Save WoW Motion",
}

WEB_DIRECTORY = "./web"
