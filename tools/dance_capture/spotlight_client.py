"""Start Spotlight for the WoW process that loaded the app-local bootstrap."""

import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-dir", type=Path, required=True)
    parser.add_argument("--client-pid", type=int, required=True)
    args = parser.parse_args()
    client = args.client_dir.resolve()
    app = Path(__file__).resolve().parent
    if app != client / "Spotlight" / "Companion":
        parser.error("Use the companion files in the selected WoW folder.")

    # The bootstrap starts Python in isolated mode, which omits the script directory.
    sys.path.insert(0, str(app))
    import spotlight_bridge
    from spotlight_http import Relay
    from spotlight_session import SpotlightSession

    settings = json.loads((app.parent / "settings.json").read_text(encoding="utf-8"))
    relay = Relay(settings["relay_url"])
    bridge_args = ["--client-dir", str(client), "--comfy-url", settings["comfy_url"]]
    if settings.get("gallery_url"):
        bridge_args.extend(("--gallery-url", settings["gallery_url"]))
    token = app.parent / "relay.token"
    if settings.get("relay_realm_auth"):
        bridge_args.extend(("--relay-url", relay.base_url, "--realm-auth"))
    elif token.is_file():
        bridge_args.extend(("--relay-url", relay.base_url, "--relay-token-file", str(token)))
    spotlight_bridge.main(bridge_args, game_pid=args.client_pid,
                          session_factory=lambda path, stormlib: SpotlightSession(path, stormlib, relay))


if __name__ == "__main__":
    main()
