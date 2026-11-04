"""Deliver a Spotlight proof through the lab's private TrinityCore console."""

import json
import os
import re
import subprocess


GUID = re.compile(r"0x00000000[0-9a-f]{8}")
PROOF = re.compile(r"[0-9a-f]{48}")
CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
CONTAINER_ENV = "SPOTLIGHT_REALM_SOAP_CONTAINER"


class RealmProofError(OSError):
    """The private realm proof service could not deliver the challenge."""


# The account-web container already has the private SOAP connection settings.
# Keep the proof off command lines and discard all details returned by pinfo.
DELIVER_IN_CONTAINER = r"""
import json
import os
import re
import sys

from app.soap_client import SoapCommandError, SoapConfig, SoapUnavailable, execute_command

guid, proof = json.load(sys.stdin)
config = SoapConfig(
    url=os.environ["TC_SOAP_URL"],
    username=os.environ["TC_SOAP_USER"],
    password=os.environ["TC_SOAP_PASSWORD"],
    timeout_seconds=3.0,
)
try:
    details = execute_command(config, f"pinfo {int(guid, 16)}")
except SoapCommandError as error:
    sys.exit(4 if "rejected the account-web SOAP credentials" in str(error) else 3)
except SoapUnavailable:
    sys.exit(4)

player_row = re.compile(
    r"^\W*Player\s+(?P<offline>\(offline\)\s+)?(?P<name>[^\s()|]+)\s+"
    r"\(GUID Full: (?P<guid>0x[0-9A-Fa-f]{16}) Type: Player Low: [0-9]+\)\s*$",
    re.MULTILINE,
)
player = player_row.search(details)
if player is None or player["guid"].lower() != guid:
    sys.exit(4)
if player["offline"]:
    sys.exit(3)
name = player["name"]
if not (name.isalpha() and 1 <= len(name) <= 24):
    sys.exit(4)
try:
    execute_command(config, f"send message {name} WSAUTH1{proof}")
except SoapCommandError as error:
    sys.exit(4 if "rejected the account-web SOAP credentials" in str(error) else 3)
except SoapUnavailable:
    sys.exit(4)
"""


def configured():
    """Validate the optional lab configuration at relay startup."""
    container = os.environ.get(CONTAINER_ENV)
    if container is None:
        return False
    if not CONTAINER.fullmatch(container):
        raise ValueError(f"Set {CONTAINER_ENV} to an account-web container name.")
    return True


def deliver(guid, proof):
    """Send a proof to the current online holder of a realm player GUID."""
    if not GUID.fullmatch(guid) or not int(guid, 16):
        return False
    if not PROOF.fullmatch(proof):
        raise ValueError("Invalid Spotlight realm proof.")
    if not configured():
        raise RealmProofError("The private realm SOAP container is not configured.")
    container = os.environ[CONTAINER_ENV]
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", container, "python", "-c", DELIVER_IN_CONTAINER],
            input=json.dumps((guid, proof)), text=True, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=9, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RealmProofError("Could not reach the private realm proof service.") from None
    if result.returncode == 3:
        return False
    if result.returncode != 0:
        raise RealmProofError("The private realm proof service failed.")
    return True
