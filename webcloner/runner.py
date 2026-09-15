"""One fixed job in a disposable, offline container. No host execution fallback."""
import os
import selectors
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

VALIDATE = "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('/workspace/input.html').read()); p.close(); print('HTML parsed successfully (not a standards validator)')"


class ContainerRunner:
    def __init__(self, image, timeout=15, output_limit=65536):
        self.image, self.timeout, self.output_limit = image, timeout, output_limit

    def run(self, workspace, filename):
        if not self.image:
            raise RuntimeError("Container execution disabled: configure a pinned image")
        docker = shutil.which("docker", path="/usr/bin:/usr/local/bin:/bin")
        if docker is None:
            raise RuntimeError("Container execution disabled: Docker unavailable")
        data = workspace.read(filename)
        # Mount only a fresh, read-only snapshot of the requested input file.
        with tempfile.TemporaryDirectory(prefix="webcloner-job-") as directory:
            os.chmod(directory, 0o755)
            target = Path(directory) / "input.html"
            target.write_bytes(data)
            target.chmod(0o444)
            return self._execute(docker, directory, VALIDATE)

    def _execute(self, docker, directory, script):
        """Trusted runner primitive; script is fixed above, never supplied by a tool request."""
        name = "webcloner-" + uuid.uuid4().hex
        env = {"PATH": "/usr/bin:/usr/local/bin:/bin", "LANG": "C.UTF-8"}
        args = [docker, "--host", "unix:///var/run/docker.sock", "run", "--rm", "--pull=never", "--name", name,
                "--network=none", "--user=65534:65534", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--read-only", "--pids-limit=32", "--memory=128m", "--memory-swap=128m", "--cpus=0.5",
                "--ulimit=nofile=64:64", "--log-driver=none", "--mount", f"type=bind,src={directory},dst=/workspace,readonly",
                "--workdir=/workspace", "--entrypoint=python3", self.image, "-I", "-B", "-c", script]
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        output = bytearray()
        deadline = time.monotonic() + self.timeout
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Container job timed out")
                    for key, _ in selector.select(timeout=min(0.1, max(0, deadline - time.monotonic()))):
                        chunk = os.read(key.fileobj.fileno(), 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        output.extend(chunk)
                        if len(output) > self.output_limit:
                            raise ValueError("Container output limit exceeded")
                code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
                if code:
                    # Avoid propagating raw runtime errors (may contain host details).
                    raise RuntimeError(f"Container job unavailable or failed (exit {code}); no host fallback")
                return output.decode("utf-8", errors="replace")
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdout.close()
            # Kill container too: killing the Docker client alone is insufficient.
            self._cleanup(docker, name, env)

    @staticmethod
    def _cleanup(docker, name, env):
        # --rm and explicit cleanup may race. Confirm absence even when rm reports
        # removal already in progress; never treat a failed client as proof of cleanup.
        for _ in range(10):
            cleanup = subprocess.run([docker, "--host", "unix:///var/run/docker.sock", "rm", "-f", name],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env=env, timeout=5)
            if cleanup.returncode == 0 or b"No such container" in cleanup.stderr:
                return
            inspect = subprocess.run([docker, "--host", "unix:///var/run/docker.sock", "container", "inspect", "--format", "{{.State.Running}}", name],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env=env, timeout=5)
            if inspect.returncode and b"No such container" in inspect.stderr:
                return
            if b"removal" not in cleanup.stderr.lower():
                break
            time.sleep(0.1)
        raise RuntimeError("Container cleanup could not be confirmed; inspect Docker before retrying")
