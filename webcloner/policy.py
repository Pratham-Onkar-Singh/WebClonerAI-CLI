import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .files import MAX_BYTES, normalize_path
from .network import normalize_url

Verdict = Literal["allow", "deny", "require_approval"]
SCHEMAS = {
    "read_file": ("read", {"filename"}),
    "list_files": ("read", {"directory"}),
    "write_file": ("write", {"filename", "content"}),
    "replace_text": ("write", {"filename", "old", "new", "mode"}),
    "fetch_url": ("fetch", {"url"}),
    "download_asset": ("fetch", {"url", "filename"}),
    "clone_page": ("fetch", {"url"}),
    "execute_command": ("process", {"job", "filename"}),
}


@dataclass(frozen=True)
class ToolRequest:
    request_id: str
    action: str
    # Canonical serialized arguments prevent mutation between decision and execution.
    arguments_json: str

    @property
    def arguments(self):
        return json.loads(self.arguments_json)

    @classmethod
    def parse(cls, action, arguments):
        if not isinstance(action, str) or action not in SCHEMAS:
            raise ValueError("Unknown tool")
        if type(arguments) is not dict or set(arguments) != SCHEMAS[action][1]:
            raise ValueError("Arguments must exactly match the tool schema")
        if any(type(v) is not str for v in arguments.values()):
            raise ValueError("Every argument must be a string")
        args = dict(arguments)
        if any(len(v.encode("utf-8")) > MAX_BYTES for v in args.values()):
            raise ValueError("Argument exceeds byte limit")
        for key in ("filename", "directory"):
            if key in args:
                args[key] = normalize_path(args[key], allow_root=key == "directory")
        if action == "execute_command":
            if args["job"] != "validate_html" or not args["filename"].endswith(".html"):
                raise ValueError("Only validate_html with an HTML filename is supported")
        if action == "replace_text":
            if args["mode"] not in ("one", "all") or not args["old"]:
                raise ValueError("replace_text requires a nonempty old value and mode one or all")
            if len(args["old"].encode()) > 65_536 or len(args["new"].encode()) > 65_536:
                raise ValueError("replace_text values exceed the focused-edit limit")
        return cls(uuid.uuid4().hex, action, json.dumps(args, sort_keys=True, separators=(",", ":")))


@dataclass(frozen=True)
class Decision:
    request_id: str
    action: str
    verdict: Verdict
    matched_rule: str
    reason: str
    policy_version: str
    evaluation_ms: float

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Policy:
    version: str
    permissions: tuple
    fetch_hosts: tuple
    container_image: str | None

    @classmethod
    def load(cls, path):
        raw = Path(path).read_bytes()
        if len(raw) > 16384:
            raise ValueError("Policy exceeds byte limit")
        data = json.loads(raw)
        if set(data) != {"version", "permissions", "fetch_hosts", "container_image"}:
            raise ValueError("Unsupported policy fields")
        if type(data["version"]) is not str or not data["version"]:
            raise ValueError("Policy version required")
        permissions = data["permissions"]
        if type(permissions) is not dict or set(permissions) != {"read", "write", "fetch", "process"}:
            raise ValueError("Exactly four permission categories required")
        if any(v not in ("allow", "deny", "require_approval") for v in permissions.values()):
            raise ValueError("Invalid permission verdict")
        hosts = data["fetch_hosts"]
        if type(hosts) is not list or len(hosts) > 100 or any(type(h) is not str or h != h.lower() or not h for h in hosts):
            raise ValueError("Expected a bounded list of lowercase exact hosts")
        image = data["container_image"]
        if image is not None:
            import re
            if type(image) is not str or not re.fullmatch(r"[a-z0-9./_-]+@sha256:[a-f0-9]{64}", image):
                raise ValueError("Container image must be pinned by sha256 digest")
        digest = hashlib.sha256(raw).hexdigest()
        return cls(data["version"] + ":" + digest, tuple(sorted(permissions.items())), tuple(hosts), image)

    def evaluate(self, request, workspace):
        start = time.perf_counter_ns()
        verdict, rule, reason = "deny", "policy.error", "Policy evaluation failed"
        try:
            args = request.arguments
            category = SCHEMAS[request.action][0]
            if "filename" in args:
                workspace.check(args["filename"])
            if "directory" in args:
                workspace.check(args["directory"], directory=True)
            if "url" in args:
                normalize_url(args["url"], self.fetch_hosts)
            verdict = dict(self.permissions)[category]
            if request.action in ("download_asset", "clone_page"):
                write = dict(self.permissions)["write"]
                verdict = "deny" if "deny" in (verdict, write) else "require_approval" if "require_approval" in (verdict, write) else "allow"
                category = "fetch+write"
            rule, reason = "permission." + category, f"Configured {category} permission: {verdict}"
            if request.action == "execute_command" and self.container_image is None:
                verdict, rule, reason = "deny", "process.disabled", "No pinned container image configured"
        except Exception:
            verdict, rule, reason = "deny", "constraint.invalid", "Path, destination, or policy constraint failed"
        return Decision(request.request_id, request.action, verdict, rule, reason, self.version, (time.perf_counter_ns() - start) / 1e6)
