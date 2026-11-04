import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "Spotlight.MotionDownload",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SpotlightSaveMotion") return;

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.call(this, message);
            const file = message.spotlight_files?.[0];
            if (!file) return;

            if (!this.spotlightDownload) {
                this.spotlightDownload = this.addWidget("button", "Download motion JSON", null, () => {
                    const current = this.spotlightFile;
                    if (!current) return;
                    const query = new URLSearchParams(current);
                    const link = document.createElement("a");
                    link.href = api.apiURL(`/view?${query}`);
                    link.download = current.filename;
                    link.click();
                }, { serialize: false });
            }
            this.spotlightFile = file;
            this.setDirtyCanvas(true, true);
        };
    },
});
