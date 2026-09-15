"""Opt-in REAL disposable-container verification; no model or image downloads."""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .dispatcher import Dispatcher
from .runner import ContainerRunner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/runner.json"))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9./_-]+@sha256:[a-f0-9]{64}", args.image):
        parser.error("A local digest-pinned image is required")
    started = time.monotonic()
    report = {"mode": "real disposable containers; trusted test scripts and automated test approval; no live model", "image": args.image,
              "command": f"python3 -m webcloner.verify_runner --image {args.image}",
              "python": platform.python_version(), "platform": platform.platform(), "checks": [], "time": time.time()}
    docker = shutil.which("docker", path="/usr/bin:/usr/local/bin:/bin")
    if not docker:
        report["blocker"] = "Docker not installed"
    else:
        version = subprocess.run([docker, "--host", "unix:///var/run/docker.sock", "version", "--format", "{{.Server.Version}}"],
                                 capture_output=True, text=True, timeout=5,
                                 env={"PATH": "/usr/bin:/usr/local/bin:/bin", "LANG": "C.UTF-8"})
        report["docker_server"] = version.stdout.strip() if version.returncode == 0 else "unavailable"
        with tempfile.TemporaryDirectory(prefix="webcloner-integration-") as base:
            config = json.loads((Path(__file__).resolve().parents[1] / "policies/default.json").read_text())
            config["container_image"] = args.image
            policy_path = Path(base) / "policy.json"
            policy_path.write_text(json.dumps(config))
            dispatcher = Dispatcher(Path(base) / "job", policy_path, Path(base) / "events.jsonl",
                                    approval_ui=lambda request, decision: True)
            workspace = dispatcher.workspace
            workspace.write("index.html", b"<!doctype html><title>fixture</title><h1>Offline</h1>")
            # Synthetic host file outside the mount, never a real credential.
            outside = Path(base) / "synthetic-secret.txt"
            outside.write_text("SYNTHETIC_HOST_SECRET")
            try:
                runner = ContainerRunner(args.image)
                result = dispatcher.dispatch("execute_command", {"job": "validate_html", "filename": "index.html"})
                assert result["ok"], result.get("error")
                assert result["decision"]["verdict"] == "require_approval"
                assert "HTML parsed successfully" in result["output"]
                report["checks"].append("fixed HTML job through dispatcher with automated trusted test approval")
                # Only trusted test harness can use _execute; no tool accepts scripts.
                script = (
                    "import os,pathlib,socket; "
                    "assert os.getuid()==65534; "
                    "assert not pathlib.Path('/var/run/docker.sock').exists(); "
                    f"assert not pathlib.Path({str(outside)!r}).exists(); "
                    "assert 'HUGGINGFACE_API_KEY' not in os.environ; "
                    "assert set(os.listdir('/sys/class/net'))=={'lo'}; "
                    "assert 'CapEff:\\t0000000000000000' in pathlib.Path('/proc/self/status').read_text(); "
                    "assert 'NoNewPrivs:\\t1' in pathlib.Path('/proc/self/status').read_text(); "
                    "print('constraints verified')"
                )
                # Mount only an empty directory; chmod lets the unprivileged UID enter it.
                with tempfile.TemporaryDirectory(prefix="webcloner-probe-") as mount:
                    os.chmod(mount, 0o755)
                    assert "constraints verified" in runner._execute(docker, mount, script)
                    report["checks"].append("unprivileged UID, no socket/host file/key, loopback only, capabilities dropped, no new privileges")
                    readonly = "import pathlib\ntry:\n pathlib.Path('/workspace/changed').write_text('x')\nexcept OSError:\n print('read only')\nelse:\n raise AssertionError('writable mount')"
                    assert "read only" in runner._execute(docker, mount, readonly)
                    report["checks"].append("read-only mount")
                    for name, test_runner, script, expected in (
                        ("bounded output", ContainerRunner(args.image, output_limit=1024), "print('x'*100000)", ValueError),
                        ("timeout and cleanup", ContainerRunner(args.image, timeout=2), "import time; time.sleep(30)", TimeoutError),
                    ):
                        try:
                            test_runner._execute(docker, mount, script)
                        except expected:
                            report["checks"].append(name)
                        else:
                            raise AssertionError(name + " did not fail closed")
                report["status"] = "passed"
            except Exception as exc:
                report["status"] = "blocked_or_failed"
                report["blocker"] = str(exc)
            finally:
                dispatcher.close()
    report["elapsed_seconds"] = time.monotonic() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
