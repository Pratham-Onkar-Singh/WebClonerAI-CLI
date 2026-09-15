"""Reproducible policy-only fixture evaluation; never executes fixture actions."""
import argparse
import hashlib
import json
import math
import os
import platform
import tempfile
from pathlib import Path

from .dispatcher import Dispatcher

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, percentile):
    return sorted(values)[max(0, math.ceil(len(values) * percentile) - 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=100)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/evaluation.json")
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 10000:
        parser.error("repetitions must be between 1 and 10000")
    report = {"mode": "offline policy-only; no execution, DNS, network, container, or model time",
              "fixture_version": "v1", "repetitions": args.repetitions,
              "python": platform.python_version(), "platform": platform.platform(), "logical_cpus": os.cpu_count(),
              "command": f"python3 -m webcloner.evaluate --repetitions {args.repetitions}", "sets": {}}
    try:
        report["cpu"] = next(line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name"))
    except (OSError, StopIteration):
        report["cpu"] = platform.machine()
    with tempfile.TemporaryDirectory(prefix="webcloner-eval-") as directory:
        base = Path(directory)
        data = json.loads((ROOT / "policies/default.json").read_text())
        data["permissions"]["write"] = "require_approval"
        approval = base / "approval.json"
        approval.write_text(json.dumps(data))
        dispatchers = {
            "default": Dispatcher(base / "job", ROOT / "policies/default.json", base / "events.jsonl"),
            "approval": Dispatcher(base / "job", approval, base / "approvals.jsonl"),
        }
        try:
            report["policy_versions"] = {k: d.policy.version for k, d in dispatchers.items()}
            for name, file in (("development", "policy-cases.json"), ("held_out", "held-out.json")):
                raw = (ROOT / "tests/fixtures/v1" / file).read_bytes()
                cases = json.loads(raw)
                counts, times, details = {}, [], []
                unsafe, benign_blocked, approval_count, mismatches = 0, 0, 0, 0
                for case in cases:
                    actuals = set()
                    for _ in range(args.repetitions):
                        _, decision = dispatchers[case.get("profile", "default")].evaluate(case["tool"], case["args"])
                        actuals.add(decision.verdict)
                        times.append(decision.evaluation_ms)
                        key = case["expected"] + " -> " + decision.verdict
                        counts[key] = counts.get(key, 0) + 1
                        unsafe += case["kind"] == "adversarial" and decision.verdict == "allow"
                        benign_blocked += case["kind"] == "benign" and case["expected"] != "deny" and decision.verdict == "deny"
                        approval_count += decision.verdict == "require_approval"
                        mismatches += decision.verdict != case["expected"]
                    details.append({"id": case["id"], "expected": case["expected"], "observed": sorted(actuals), "rationale": case["rationale"]})
                report["sets"][name] = {"unique_cases": len(cases), "samples": len(times), "fixture_sha256": hashlib.sha256(raw).hexdigest(),
                    "confusion_counts": counts, "unsafe_actions_incorrectly_allowed": unsafe,
                    "benign_actions_incorrectly_blocked": benign_blocked, "approval_required": approval_count,
                    "mismatches": mismatches, "policy_p50_ms": percentile(times, 0.50), "policy_p95_ms": percentile(times, 0.95), "cases": details}
        finally:
            for dispatcher in dispatchers.values():
                dispatcher.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({name: {k: v for k, v in value.items() if k != "cases"} for name, value in report["sets"].items()}, indent=2))
    return int(any(s["mismatches"] for s in report["sets"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
