import json
import os
import stat
import time
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .redaction import redact


def protected_path(path, workspace):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Protected paths must not contain symlinks")
    if path.resolve().is_relative_to(workspace.root):
        raise ValueError("Policy and audit files must be outside the agent workspace")
    return path


def sanitized_arguments(args):
    # Never log generated page bodies, replacement values, or URL query values.
    hidden_bodies = {"content", "old", "new"}
    sanitized = {}
    for key, value in args.items():
        if key in hidden_bodies and isinstance(value, str):
            sanitized[key] = {"bytes": len(value.encode())}
        elif key == "url" and isinstance(value, str):
            parsed = urlsplit(value)
            sanitized[key] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            if parsed.query:
                sanitized["url_query_sha256"] = sha256(parsed.query.encode()).hexdigest()
        else:
            sanitized[key] = value
    return redact(sanitized)


class Audit:
    def __init__(self, path, workspace):
        self.path = protected_path(path, workspace)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(self.fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            os.close(self.fd)
            raise ValueError("Audit must be a regular file with one link")

    def emit(self, event, **fields):
        data = (json.dumps(redact({"time": time.time(), "event": event, **fields}), ensure_ascii=True) + "\n").encode()
        if os.write(self.fd, data) != len(data):
            raise OSError("Incomplete audit write")
        os.fsync(self.fd)

    def close(self):
        os.close(self.fd)
