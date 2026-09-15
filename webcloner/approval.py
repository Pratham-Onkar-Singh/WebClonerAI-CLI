import hashlib
import secrets
import time


class Approvals:
    """In-memory capabilities held by trusted code, never accepted as model arguments."""
    def __init__(self, audit, clock=time.monotonic):
        self.audit, self.clock = audit, clock
        self.pending = {}

    @staticmethod
    def binding(request, version):
        return hashlib.sha256((request.request_id + "\0" + request.action + "\0" + request.arguments_json + "\0" + version).encode()).hexdigest()

    def issue(self, request, version, ttl=60):
        token = secrets.token_urlsafe(32)
        self.pending[token] = (self.binding(request, version), self.clock() + ttl)
        self.audit.emit("approval.granted", request_id=request.request_id, policy_version=version, expires_in_seconds=ttl)
        return token

    def consume(self, token, request, version):
        item = self.pending.pop(token, None)
        ok = item is not None and item[0] == self.binding(request, version) and self.clock() < item[1]
        self.audit.emit("approval.consumed" if ok else "approval.rejected", request_id=request.request_id)
        return ok
