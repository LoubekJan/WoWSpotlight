"""Start Spotlight for the WoW process that loaded the app-local bootstrap."""

import argparse
from ipaddress import IPv6Address
import json
from pathlib import Path
import re
import sys


SERVICE_PORTS = {"comfy_url": 8188, "gallery_url": 9093, "relay_url": 8765}
REALMLIST_ENTRY = re.compile(r'^\s*set\s+realmlist\s+(?:"([^"]+)"|([^\s#;]+))(?=\s|$)', re.IGNORECASE)
HOST_AND_PORT = re.compile(r"(\[[0-9a-fA-F:.]+\]|[A-Za-z0-9.-]+)(?::([0-9]{1,5}))?")


def realm_host(address):
    """Return a URL-ready host, without the optional realm login port."""
    if address.count(":") > 1 and not address.startswith("["):
        return f"[{IPv6Address(address)}]"
    parts = HOST_AND_PORT.fullmatch(address)
    if not parts or (parts[2] and not 1 <= int(parts[2]) <= 65535):
        raise ValueError("Use a hostname or IP address in the 'set realmlist' line.")
    host = parts[1]
    if host.startswith("["):
        return f"[{IPv6Address(host[1:-1])}]"
    labels = host.removesuffix(".").split(".")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        raise ValueError("Use a valid hostname in the 'set realmlist' line.")
    return host


def service_urls(client, settings):
    urls = {}
    for key in SERVICE_PORTS:
        value = settings.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"Set {key} to a URL in Spotlight/settings.json.")
            if value.strip():
                urls[key] = value.strip()
    if len(urls) != len(SERVICE_PORTS):
        path = client / "Data" / "enUS" / "realmlist.wtf"
        address = None
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            entry = REALMLIST_ENTRY.match(line)
            if entry:
                address = entry[1] or entry[2]
        if not address:
            raise ValueError(f"Add a 'set realmlist' line to {path} or set the service URLs in Spotlight/settings.json.")
        host = realm_host(address)
        for key, port in SERVICE_PORTS.items():
            urls.setdefault(key, f"http://{host}:{port}")
    return urls


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

    token = app.parent / "relay.token"
    settings_path = app.parent / "settings.json"
    try:
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            settings = {}
        if not isinstance(settings, dict):
            raise ValueError("Spotlight/settings.json must contain a JSON object.")
        urls = service_urls(client, settings)
        relay = Relay(urls["relay_url"])
        realm_auth = settings.get("relay_realm_auth", not token.is_file())
        if not realm_auth and token.is_file() and not (settings.get("relay_url") or "").strip():
            raise ValueError("Set relay_url explicitly in Spotlight/settings.json when using a relay.token file.")
    except (OSError, ValueError) as error:
        from tkinter import messagebox
        messagebox.showerror("Spotlight", str(error))
        return
    bridge_args = ["--client-dir", str(client), "--comfy-url", urls["comfy_url"],
                   "--gallery-url", urls["gallery_url"]]
    if realm_auth:
        bridge_args.extend(("--relay-url", relay.base_url, "--realm-auth"))
    elif token.is_file():
        bridge_args.extend(("--relay-url", relay.base_url, "--relay-token-file", str(token)))
    spotlight_bridge.main(bridge_args, game_pid=args.client_pid,
                          session_factory=lambda path, stormlib: SpotlightSession(path, stormlib, relay))


if __name__ == "__main__":
    main()
