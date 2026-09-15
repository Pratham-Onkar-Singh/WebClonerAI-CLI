import json
import time
import uuid

from .approval import Approvals
from .audit import Audit, protected_path, sanitized_arguments
from .content import compact_file_content, compact_web_content
from .files import Workspace
from .network import Fetcher
from .policy import Decision, Policy, ToolRequest
from .redaction import redact
from .runner import ContainerRunner
from .snapshot import StaticPageCloner


class Dispatcher:
    def __init__(self, workspace, policy_path, audit_path, approval_ui=None):
        self.workspace = Workspace(workspace)
        try:
            self.policy_path = protected_path(policy_path, self.workspace)
            if self.policy_path == protected_path(audit_path, self.workspace):
                raise ValueError("Policy and audit paths must be distinct")
            self.policy = Policy.load(self.policy_path)
            self.audit = Audit(audit_path, self.workspace)
        except BaseException:
            self.workspace.close()
            raise
        self.approvals = Approvals(self.audit)
        self.approval_ui = approval_ui
        self.fetcher = Fetcher(self.policy.fetch_hosts)
        self.runner = ContainerRunner(self.policy.container_image)

    def close(self):
        self.workspace.close()
        self.audit.close()

    def evaluate(self, action, arguments):
        start = time.perf_counter_ns()
        try:
            request = ToolRequest.parse(action, arguments)
            decision = self.policy.evaluate(request, self.workspace)
            # Include schema validation in policy latency; no DNS/network or logging.
            decision = Decision(**{**decision.to_dict(), "evaluation_ms": (time.perf_counter_ns() - start) / 1e6})
            return request, decision
        except Exception:
            return None, Decision(uuid.uuid4().hex, action if isinstance(action, str) and len(action) < 100 else "invalid",
                                  "deny", "schema.invalid", "Unknown tool, malformed arguments, or policy error",
                                  self.policy.version, (time.perf_counter_ns() - start) / 1e6)

    def dispatch(self, action, arguments):
        request, decision = self.evaluate(action, arguments)
        result = {"decision": decision.to_dict(), "ok": False}
        # Failure to record intent prevents execution; no tool runs before this write.
        self.audit.emit("intent", decision=decision.to_dict(), arguments=sanitized_arguments(request.arguments) if request else {"invalid": True})
        if request is None or decision.verdict == "deny":
            result["error"] = decision.reason
        else:
            try:
                token = None
                if decision.verdict == "require_approval":
                    self.audit.emit("approval.requested", request_id=request.request_id)
                    if self.approval_ui is None or self.approval_ui(request, decision) is not True:
                        self.audit.emit("approval.denied", request_id=request.request_id)
                        raise PermissionError("Trusted human approval required")
                    token = self.approvals.issue(request, self.policy.version)
                # Trusted config changes invalidate existing approvals and require restart.
                protected_path(self.policy_path, self.workspace)
                if Policy.load(self.policy_path).version != self.policy.version:
                    raise PermissionError("Policy changed; restart and request fresh approval")
                recheck = self.policy.evaluate(request, self.workspace)
                if recheck.verdict != decision.verdict:
                    raise PermissionError("Execution constraints changed")
                if token is not None and not self.approvals.consume(token, request, self.policy.version):
                    raise PermissionError("Approval invalid or expired")
                output = self._execute(request)
                result.update(ok=True, output=redact(output))
            except Exception as exc:
                result["error"] = redact(str(exc))
        self.audit.emit("outcome", request_id=decision.request_id, action=decision.action, ok=result["ok"], error=result.get("error"))
        return redact(result)

    def _execute(self, request):
        args = request.arguments
        match request.action:
            case "read_file":
                return compact_file_content(self.workspace.read(args["filename"]), args["filename"])
            case "list_files":
                return self.workspace.list(args["directory"])
            case "write_file":
                self.workspace.write(args["filename"], args["content"].encode())
                return "File written"
            case "replace_text":
                source = self.workspace.read(args["filename"]).decode("utf-8")
                count = source.count(args["old"])
                if count == 0:
                    raise ValueError("Target text was not found")
                if args["mode"] == "one" and count != 1:
                    raise ValueError("Target text is ambiguous; use mode all or a more specific value")
                self.workspace.write(args["filename"], source.replace(args["old"], args["new"], -1 if args["mode"] == "all" else 1).encode())
                return {"filename": args["filename"], "replacements": count if args["mode"] == "all" else 1}
            case "fetch_url":
                return compact_web_content(self.fetcher.fetch(args["url"]), args["url"])
            case "download_asset":
                data = self.fetcher.fetch(args["url"])
                self.workspace.write(args["filename"], data)
                return {"filename": args["filename"], "bytes": len(data)}
            case "clone_page":
                return StaticPageCloner(self.fetcher, self.workspace).clone(args["url"])
            case "execute_command":
                return self.runner.run(self.workspace, args["filename"])
            case _:
                raise PermissionError("Unsupported operation")
