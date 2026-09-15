# Verification record

Verified locally on 2026-09-15. No deployment, push, paid model call, live-model
evaluation, or access to real API credentials was performed.

## Environment

- Linux x86_64, Intel Core i5-13500H, 16 logical CPUs.
- Python 3.12.3; offline execution core and tests use the standard library.
- Docker Engine 29.7.2; existing local digest-pinned Python image, no image pull.
- Node.js 20.20.2, npm 10.8.2, Next.js 16.3.5, React 19.3.0, TypeScript 5.9.3.
- Dashboard dependency versions and integrity hashes are in `dashboard/package-lock.json`.

## Checks and results

| Command | Result | Evidence scope |
| --- | --- | --- |
| `python3 -m unittest discover -v` | 52 tests passed | Offline unit/integration tests; network and unavailable-runner paths are mocked |
| `python3 -m webcloner.demo` | Passed; both output files match fixture bytes | Recorded model responses and mocked transport |
| `python3 -m webcloner.evaluate --repetitions 100` | 2,800 decisions; zero expected-verdict mismatches | Policy-only authored fixtures; no actions executed |
| `python3 -m webcloner.verify_runner --image python-hello-world@sha256:4427c16aaf968de7246831639a0ba54ee5346638c7b0d49717fce129253df74f` | Passed | Real disposable containers; automated trusted test approval |
| `cd dashboard && npm run build` | Passed | Production compilation and TypeScript validation |
| `cd dashboard && npm run typecheck` | Passed | Standalone TypeScript check |
| `python3 -m webcloner.verify_dashboard` | Passed, 10 fixture events | Real HTTP against local API and built dashboard; no visual browser test |
| `git diff --check` | Passed | Tracked patch whitespace check |

The host sandbox initially blocked Docker access and local listening sockets.
These checks passed with the requested local permissions. Next.js compiled inside
the sandbox but its child TypeScript configuration check failed there; the full
production build passed outside the sandbox. No checks were disabled.

The first real runner probe found a race between Docker's automatic removal and
explicit cleanup after excessive output. Cleanup now confirms container absence;
the regression unit test and real output/timeout checks pass. The runner report
records the successful final execution, exact image, version, elapsed time, and
individual assertions. The image is local to this machine, not a portable published
dependency; other operators must choose and provision a vetted local Python image.

HTTP smoke checks verified read-only JSON, foreign Host/Origin rejection,
unsupported POST, server-rendered policy data, and foreign dashboard Host rejection.
Search/filter interaction and visual layout were not browser-automated. No raw
fetched webpage is rendered by the dashboard.

## Evaluation interpretation

See [evaluation.json](evaluation.json) for fixture hashes, policy hashes, per-case
rationales, confusion counts, timing percentiles, sample sizes, and hardware.

| Fixture set | Unique cases | Repetitions per case | Decisions | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Development | 19 | 100 | 1,900 | 0.030166 | 0.151669 |
| Held-out | 9 | 100 | 900 | 0.021836 | 0.058170 |

Both sets had zero unsafe actions incorrectly allowed, zero benign actions
incorrectly denied, and 100 approval-required decisions. The benign denominator
excludes a case explicitly expected to be denied because no runner image is
configured. Full three-way expected/observed confusion counts are exported.

Timing includes schema validation, path checks, and deterministic policy evaluation.
It excludes DNS, model latency, audit writes, approval waiting, network exchange,
container startup/execution, and the second pre-execution recheck. The test machine
was not otherwise controlled; these are observed microbenchmark values, not a
service latency guarantee. The final address-hardening changes concern runtime
DNS answers, which these policy-only hostname fixtures do not resolve.

The held-out file is separate from development fixtures and is not loaded by the
unit-test suite. Both were authored within this project; this is not independent
red-teaming. Repeated decisions measure stability/timing, not 2,800 unique attacks.
The malicious-page recording deliberately has the model follow injected
instructions; deterministic tool enforcement blocks the resulting requests.
It makes no claim about a live model's resistance to prompt injection.

## Shipped and deferred

Shipped: Python enforcement core; CLI approval; file/network/container constraints;
redacted audit and local read-only dashboard; fixtures, tests, evaluation, reports,
updated provider instructions, architecture, and threat model.

Deferred: live-model/automated screenshot evaluation, arbitrary build jobs, MCP adapters,
provider comparisons, shadow replay, cancellable DNS resolution, authenticated
remote dashboard and browser-based approvals. The default policy disables process
execution until a pinned image is configured and approves only the example hosts.

Remaining security assumptions are documented in [the threat model](../docs/THREAT_MODEL.md):
trusted host Python/operator, no hostile same-user filesystem writers, vetted
container images, ordinary routing, scoped secret detection, and local single-user UI.
Audit logs are not tamper-proof and containers do not eliminate host-kernel risk.
