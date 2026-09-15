"""Linux descriptor-relative file access. Reject symlinks and hardlinked files."""
import os
import re
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

MAX_BYTES = 1_000_000


def normalize_path(value, allow_root=False):
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("Path must be a nonempty string of at most 512 characters")
    if value == "." and allow_root:
        return value
    # Deliberately portable, narrow filename grammar. No hidden/config files.
    parts = value.split("/")
    if any(p in ("", ".", "..") or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", p) for p in parts):
        raise ValueError("Only relative paths with ordinary filename components are supported")
    return "/".join(parts)


class Workspace:
    def __init__(self, root):
        root = Path(root).absolute()
        if any(p.is_symlink() for p in (root, *root.parents)):
            raise ValueError("Workspace ancestors must not be symlinks")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    @contextmanager
    def parent(self, path, create=False):
        parts = normalize_path(path).split("/")
        fd = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd, parts[-1]
        finally:
            os.close(fd)

    @staticmethod
    def regular(info):
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Only regular files with one hard link are supported")

    def check(self, path, directory=False):
        if directory and path == ".":
            return
        try:
            with self.parent(path) as (fd, leaf):
                info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
                if directory:
                    if not stat.S_ISDIR(info.st_mode):
                        raise ValueError("Expected a directory, not a symlink or file")
                else:
                    self.regular(info)
        except FileNotFoundError:
            # New paths are permitted; parent() revalidates every component at use.
            return

    def read(self, path):
        with self.parent(path) as (fd, leaf):
            raw = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(raw, "rb") as stream:
                self.regular(os.fstat(stream.fileno()))
                data = stream.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError("File exceeds byte limit")
                return data

    def write(self, path, data):
        if len(data) > MAX_BYTES:
            raise ValueError("File exceeds byte limit")
        with self.parent(path, create=True) as (fd, leaf):
            try:
                self.regular(os.stat(leaf, dir_fd=fd, follow_symlinks=False))
            except FileNotFoundError:
                pass
            temporary = ".write-" + uuid.uuid4().hex
            raw = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                with os.fdopen(raw, "wb") as stream:
                    stream.write(data)
                os.replace(temporary, leaf, src_dir_fd=fd, dst_dir_fd=fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=fd)
                except FileNotFoundError:
                    pass

    def list(self, path):
        if path == ".":
            fd = os.dup(self.fd)
        else:
            with self.parent(path) as (parent, leaf):
                fd = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            # Bound enumeration, including directories with many entries.
            with os.scandir(fd) as entries:
                names = []
                for entry in entries:
                    if len(names) >= 1000:
                        raise ValueError("Directory exceeds entry limit")
                    names.append(entry.name)
                return sorted(names)
        finally:
            os.close(fd)
