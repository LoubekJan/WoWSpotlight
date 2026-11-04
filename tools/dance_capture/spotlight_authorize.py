"""Bind temporary Spotlight publishing credentials to logged-in realm characters."""

from collections import deque
from hmac import compare_digest
from http import HTTPStatus
import re
from secrets import token_hex, token_urlsafe
from threading import Lock
from time import monotonic


PROOF = re.compile(r"[a-f0-9]{48}")
PROOF_SECONDS = 75
RETRY_SECONDS = 20
SESSION_SECONDS = 6 * 60 * 60


class ProofError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class RealmAuthorization:
    def __init__(self, deliver):
        self.deliver = deliver
        self.lock = Lock()
        self.challenges = {}
        self.sessions = {}
        self.recent = deque()

    def issue(self, actor, peer):
        now = monotonic()
        with self.lock:
            while self.recent and self.recent[0][0] <= now - 60:
                self.recent.popleft()
            if (len(self.recent) >= 128 or sum(addr == peer for _, _, addr in self.recent) >= 16
                    or any(guid == actor and at > now - RETRY_SECONDS for at, guid, _ in self.recent)):
                raise ProofError(HTTPStatus.TOO_MANY_REQUESTS, "Wait for realm verification before trying again.")
            self.recent.append((now, actor, peer))
            self.challenges = {guid: item for guid, item in self.challenges.items() if item[2] > now}
            code = token_hex(24)
            self.challenges[actor] = (code, peer, now + PROOF_SECONDS)
        try:
            delivered = self.deliver(actor, code)
        except (OSError, RuntimeError, ValueError):
            delivered = False
        if not delivered:
            with self.lock:
                current = self.challenges.get(actor)
                if current and current[0] == code:
                    del self.challenges[actor]
            raise ProofError(HTTPStatus.SERVICE_UNAVAILABLE, "Could not verify the character on the realm.")

    def redeem(self, actor, peer, code):
        now = monotonic()
        with self.lock:
            expected = self.challenges.get(actor)
            if (not expected or expected[1] != peer or expected[2] <= now
                    or not compare_digest(expected[0], code)):
                raise ProofError(HTTPStatus.UNAUTHORIZED, "Realm verification expired or was invalid.")
            del self.challenges[actor]
            self.sessions = {token: item for token, item in self.sessions.items() if item[1] > now}
            token = token_urlsafe(32)
            self.sessions[token.encode("ascii")] = (actor, now + SESSION_SECONDS)
        return {"token": token, "expires_in": SESSION_SECONDS}

    def allows(self, token, actor):
        with self.lock:
            session = self.sessions.get(token)
            return bool(session and session[1] > monotonic() and (actor is None or session[0] == actor))
