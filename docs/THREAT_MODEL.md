# Threat model and enforcement scope

## Assets and trust boundaries

Untrusted inputs are user-supplied target URLs, model JSON, fetched HTML/CSS/assets,
and generated files. The host interpreter, dispatcher, policy file, approval UI,
operator, Docker daemon, and configured image are trusted. Model output is parsed
as data; it cannot import Python or invoke an internal method.

Protect host credentials, files outside the selected output workspace, policy, and
audit records from **tool-mediated** access. The Python process still has its user's
OS privileges. This is not a sandbox for malicious Python plugins, a compromised
interpreter, a malicious operator, or another process running as the same user.

| Scenario | Boundary | Evidence |
| --- | --- | --- |
| Model accidentally emits an absolute path | Exact schema and relative path grammar | Path tests |
| Malicious arguments request shell commands or flags | Fixed `validate_html` job only | Schema and runner tests |
| Page tells model to read secrets or change policy | Same dispatcher regardless of instruction origin | Recorded malicious-page integration test |
| Symlink/hardlink reaches host data | Descriptor-relative traversal, no-follow flags, regular-file/link checks; atomic writes | Link and check/use swap tests |
| Redirect or DNS rebinding targets private services | Exact host allowlist; all returned addresses must be public; TLS connects to one checked numeric IP | Mocked transport/DNS/TLS wiring tests |
| Model invents approval | Tool schema rejects tokens; capabilities are internal, one-use, expire, and bind request/action/arguments/policy | Approval tests |
| Policy throws or audit intent cannot be written | Fail before execution | Failure-injection tests |
| Allowed process tries to reach host state | Disposable offline container; only requested input snapshot mounted read-only | Opt-in real integration report |

## Files and process constraints

The workspace is an explicit directory, not the current working directory. Paths
must be relative ASCII components, with no dot/parent/empty components, backslashes,
hidden files, or shell characters. `.` is only accepted for listing the root.
Existing symlinks and nonregular or multiply linked files are rejected. New parent
directories are opened with directory FDs and `O_NOFOLLOW`; writes use a new inode
and atomic replacement. Listing does not create directories.

These APIs prevent the tested link swaps. A hostile local process can still rename
an already-open directory outside the workspace or modify an opened inode. Do not
share writable output directories with hostile host processes. Container jobs get a
fresh snapshot rather than the live output tree. No arbitrary generated code runs.
The file tools remain trusted host-side code; `cwd` is not an isolation mechanism.

The runner has a fixed Python entrypoint, no shell, no network, UID/GID 65534,
read-only root and mount, dropped capabilities, no new privileges, PID/memory/CPU/
file-descriptor limits, a deadline, and bounded combined output. It supplies only
PATH/LANG to the Docker client and passes no host credentials into the container.
Images may have their own environment: use a vetted image without baked-in secrets.
The runner uses only the local Unix Docker socket and never pulls an image. It
attempts container removal even on timeout/output overflow and fails if removal
cannot be confirmed. Daemon failure may still require operator cleanup. Containers
share the host kernel and do not eliminate kernel/runtime/image vulnerabilities.

## Network

Only explicitly configured HTTPS hosts and port 443 are accepted; approvals cannot
override the allowlist. Every redirect repeats validation and DNS resolution. All
answers must be public unicast addresses. Numeric connections avoid a second DNS
lookup; certificate verification and SNI use the original host. IPv4-mapped IPv6,
private, loopback, link-local, multicast, and unspecified destinations fail closed.
Alternative IPv4 encodings are checked after resolution. IPv6 is conservatively
restricted to unscoped native global-unicast addresses in 2000::/3; 6to4, Teredo,
and NAT64 translation addresses are unsupported. The IPv4 protocol-assignment
block 192.0.0.0/24 is also rejected, avoiding classification differences in older
Python versions. Proxy environment variables
are not used. Redirect count is bounded; compressed responses are rejected; response
data is capped at 1 MB. A timer interrupts slow HTTP reads, alongside socket timeouts.

Remaining limit: the OS DNS resolver can block beyond the 15-second fetch deadline;
there is no cancellable resolver process in this MVP. DNS is excluded from policy
timing. Public classification does not account for unusual host routing, a public
service proxying private data, or an approved remote host behaving maliciously.
URL query values are removed from audit records and model-visible tool summaries,
but the full URL is necessarily sent to the approved host. A query supplied in the
original user prompt also remains part of a model-backed provider request; do not
put credentials, signed URLs, or sensitive data in model-backed prompts. There is
no complete information-flow control. The provider SDK has a separate trusted
network path to Hugging Face Router, outside the website-fetch policy.

## Approvals, logs, and UI

The CLI displays the exact request and policy decision, a content hash, and requires
the request ID from a terminal. Redaction may hide secret-pattern content; the hash
still binds the original bytes. The capability binds request ID, action, canonical
arguments, full policy-content hash, and monotonic expiry. It is consumed once.
Policy is reloaded and constraints rechecked immediately before execution. Changed
policy requires a restart. Capabilities disappear when the process exits. A trusted
operator can still mistakenly approve an unwanted action.

Audit intent precedes execution; outcome and approval events follow. Generated file
content is represented by byte count. Returned text and errors are redacted before
model observations or logging. Detection covers `sk-…`, `hf_…`, simple key/token
assignments, and PEM private-key blocks. This is scoped synthetic-pattern detection,
not complete DLP; encoding, split tokens, and other secret formats can evade it.

Audit and policy must be outside output and cannot be changed by supported tools.
Logs are owner-mode 0600 on creation, append-only by this application, fsynced, and
**not tamper-proof**. A host user or crash can alter or truncate them. An outcome
logging failure cannot undo an already-completed side effect. Rotate/archive logs
manually; the viewer reads only a bounded tail.

The Python API is a loopback-only read-only development service. It rejects foreign
Host and browser Origin headers, has no CORS permissions, and offers no execution,
policy editing, or approval endpoints. Next.js fetches it server-side and renders
event content as escaped text. Use port 3000 and a local single-user machine; there
is no multi-user authentication, remote deployment hardening, or availability SLA.
Generated webpages are never embedded in the dashboard. Treat opening generated
JavaScript in a browser as a separate trust decision.

The deterministic static snapshot removes script elements, inline event handlers,
frames, embeds, and JavaScript URLs before writing `index.html`. This materially
reduces active content but is deliberately scoped transformation, not a general
HTML sanitizer. Generated HTML/CSS and downloaded media remain untrusted. Serve
snapshots from a disposable local origin and do not treat them as safe input to
privileged browser automation.

## API references consulted

- [Python descriptor-relative and no-follow file APIs](https://docs.python.org/3/library/os.html)
- [Python HTTP/TLS connection APIs](https://docs.python.org/3/library/http.client.html)
- [Python IP address classification and transition-address APIs](https://docs.python.org/3/library/ipaddress.html)
- [Docker run resource and security controls](https://docs.docker.com/engine/containers/run/)
- [Next.js installation](https://nextjs.org/docs/app/getting-started/installation)
- [Next.js server fetch behavior](https://nextjs.org/docs/app/api-reference/functions/fetch)
