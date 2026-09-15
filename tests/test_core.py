import contextlib
import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent import extract_first_json, run_loop, run_static_clone, simple_clone_target
from webcloner.demo import FIXTURES, FixtureTransport, recording
from webcloner.dispatcher import Dispatcher
from webcloner.policy import ToolRequest

ROOT = Path(__file__).resolve().parents[1]
SECRET = "sk-syntheticSecret0123456789"


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.policy_path = self.base / "policy.json"
        self.policy_path.write_bytes((ROOT / "policies/default.json").read_bytes())
        self.d = Dispatcher(self.base / "output", self.policy_path, self.base / "events.jsonl")

    def tearDown(self):
        self.d.close()
        self.temp.cleanup()

    def events(self):
        return [json.loads(line) for line in (self.base / "events.jsonl").read_text().splitlines()]

    def approval_policy(self):
        data = json.loads(self.policy_path.read_text())
        data["permissions"]["write"] = "require_approval"
        self.policy_path.write_text(json.dumps(data))
        self.d.close()
        self.d = Dispatcher(self.base / "output", self.policy_path, self.base / "events.jsonl")

    def test_clone_recording(self):
        self.d.fetcher = FixtureTransport()
        responses = iter(recording())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(run_loop(self.d, lambda _: json.dumps(next(responses)), "Clone fixture"))
        self.assertEqual((self.base / "output/index.html").read_bytes(), (FIXTURES / "site.html").read_bytes())
        self.assertEqual((self.base / "output/styles.css").read_bytes(), (FIXTURES / "styles.css").read_bytes())
        self.assertEqual([e["ok"] for e in self.events() if e["event"] == "outcome"], [True] * 5)

    def test_paths(self):
        for path in ("../secret", "/etc/passwd", "assets/../../secret", "a/../b", "a//b", "./a", "a\\b", ".env", "a/./b", "a\x00b"):
            with self.subTest(path=path):
                for tool, args in (("read_file", {"filename": path}), ("write_file", {"filename": path, "content": "x"}), ("list_files", {"directory": path})):
                    self.assertEqual(self.d.dispatch(tool, args)["decision"]["verdict"], "deny")

    def test_symlink_and_hardlink(self):
        outside = self.base / "synthetic-secret.txt"
        outside.write_text(SECRET)
        (self.base / "output/link").symlink_to(self.base, target_is_directory=True)
        (self.base / "output/direct").symlink_to(outside)
        os.link(outside, self.base / "output/hard")
        for path in ("link/synthetic-secret.txt", "link/new.txt", "direct", "hard"):
            for tool, args in (("read_file", {"filename": path}), ("write_file", {"filename": path, "content": "changed"})):
                self.assertEqual(self.d.dispatch(tool, args)["decision"]["verdict"], "deny")
        self.assertEqual(outside.read_text(), SECRET)

    def test_check_use_symlink_swap(self):
        self.d.workspace.write("safe/index.html", b"original")
        original = self.d._execute
        def swap(request):
            (self.base / "output/safe").rename(self.base / "output/old")
            (self.base / "output/safe").symlink_to(self.base, target_is_directory=True)
            return original(request)
        with patch.object(self.d, "_execute", side_effect=swap):
            self.assertFalse(self.d.dispatch("write_file", {"filename": "safe/index.html", "content": "escape"})["ok"])
        self.assertFalse((self.base / "index.html").exists())

    def test_atomic_write_does_not_follow_leaf_swap(self):
        self.d.workspace.write("index.html", b"original")
        outside = self.base / "synthetic-secret.txt"
        outside.write_text(SECRET)
        original = os.replace
        def swap(src, dst, **kwargs):
            (self.base / "output/index.html").unlink()
            (self.base / "output/index.html").symlink_to(outside)
            return original(src, dst, **kwargs)
        with patch("webcloner.files.os.replace", side_effect=swap):
            self.assertTrue(self.d.dispatch("write_file", {"filename": "index.html", "content": "safe"})["ok"])
        self.assertEqual(outside.read_text(), SECRET)

    def test_malformed_and_shell(self):
        bad = [("unknown", {}), ([], {}), ("write_file", []), ("read_file", {"filename": 12}),
               ("write_file", {"filename": "x"}), ("read_file", {"filename": "x", "approval": "yes"}),
               ("write_file", {"filename": "x", "content": "x" * 1_000_001}),
               ("replace_text", {"filename": "index.html", "old": "", "new": "blue", "mode": "all"}),
               ("replace_text", {"filename": "index.html", "old": "orange", "new": "blue", "mode": "many"}),
               ("execute_command", {"command": "cat /etc/passwd; echo owned"}),
               ("execute_command", {"job": "sh", "filename": "index.html"}),
               ("execute_command", {"job": "validate_html", "filename": "index.html;id"}),
               ("execute_command", {"job": "validate_html", "filename": "index.html", "flags": "--privileged"})]
        with patch.object(self.d, "_execute") as execute:
            for action, args in bad:
                self.assertEqual(self.d.dispatch(action, args)["decision"]["verdict"], "deny")
            execute.assert_not_called()

    def test_focused_replace_is_bounded_audited_and_unambiguous(self):
        self.d.workspace.write("index.html", b'<div style="color:#ff6600">one</div><span>#ff6600</span>')
        ambiguous = self.d.dispatch("replace_text", {
            "filename": "index.html", "old": "#ff6600", "new": "#0000ff", "mode": "one",
        })
        self.assertFalse(ambiguous["ok"])
        result = self.d.dispatch("replace_text", {
            "filename": "index.html", "old": "#ff6600", "new": "#0000ff", "mode": "all",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["output"]["replacements"], 2)
        self.assertNotIn("#ff6600", self.d.workspace.read("index.html").decode())
        logged = (self.base / "events.jsonl").read_text()
        self.assertNotIn("#0000ff", logged)
        self.assertIn('"old": {"bytes": 7}', logged)

    def test_audit_redacts_url_query_values(self):
        self.d.fetcher = FixtureTransport()
        result = self.d.dispatch("fetch_url", {"url": "https://example.com/page?token=private-value"})
        self.assertFalse(result["ok"])  # Fixture transport has no query-string fixture.
        logged = (self.base / "events.jsonl").read_text()
        self.assertNotIn("private-value", logged)
        self.assertIn("url_query_sha256", logged)

    def test_clone_page_crosses_dispatcher(self):
        self.d.fetcher = FixtureTransport()
        with patch("webcloner.dispatcher.StaticPageCloner.clone", return_value={"index": "index.html"}) as clone:
            result = self.d.dispatch("clone_page", {"url": "https://example.com/"})
        self.assertTrue(result["ok"])
        clone.assert_called_once_with("https://example.com/")

    def test_model_clone_page_continues_with_its_observation(self):
        snapshots = []
        responses = iter([
            '{"step":"TOOL","tool_name":"clone_page","tool_args":{"url":"https://example.com/"}}',
            '{"step":"OUTPUT","content":"The requested follow-up edit is complete."}',
        ])
        def respond(messages):
            snapshots.append([dict(message) for message in messages])
            return next(responses)
        with patch.object(self.d, "dispatch", return_value={
            "decision": {"verdict": "allow"}, "ok": True,
            "output": {"index": "index.html", "localized_resources": 4},
        }), contextlib.redirect_stdout(io.StringIO()) as console:
            self.assertTrue(run_loop(self.d, respond, "Clone fixture and change a color"))
        self.assertEqual(len(snapshots), 2)
        observation = json.loads(snapshots[1][-1]["content"])
        self.assertEqual(observation["step"], "OBSERVE")
        self.assertEqual(observation["content"]["output"]["index"], "index.html")
        self.assertIn("follow-up edit", console.getvalue())

    def test_repeated_read_does_not_resend_large_preview(self):
        snapshots = []
        responses = iter([
            '{"step":"TOOL","tool_name":"read_file","tool_args":{"filename":"index.html"}}',
            '{"step":"TOOL","tool_name":"read_file","tool_args":{"filename":"index.html"}}',
            '{"step":"OUTPUT","content":"Finished"}',
        ])
        def respond(messages):
            snapshots.append([dict(message) for message in messages])
            return next(responses)
        def dispatch(_action, _arguments):
            return {"decision": {"verdict": "allow"}, "ok": True, "output": "x" * 20_000}
        with patch.object(self.d, "dispatch", side_effect=dispatch), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(run_loop(self.d, respond, "change a color"))
        observation = json.loads(snapshots[2][-1]["content"])
        self.assertIn("already provided", observation["content"]["output"]["notice"])

    def test_second_think_requires_an_action(self):
        snapshots = []
        responses = iter([
            '{"step":"THINK","content":"First plan"}',
            '{"step":"THINK","content":"Repeated plan"}',
            '{"step":"OUTPUT","content":"Finished"}',
        ])
        def respond(messages):
            snapshots.append([dict(message) for message in messages])
            return next(responses)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(run_loop(self.d, respond, "change a color"))
        self.assertIn("Do not THINK again", snapshots[2][-1]["content"])

    def test_simple_clone_uses_deterministic_fast_path(self):
        self.assertEqual(simple_clone_target("Clone https://www.example.com/"), "https://www.example.com/")
        self.assertEqual(simple_clone_target(" clone https://example.com/path. "), "https://example.com/path")
        self.assertIsNone(simple_clone_target("Inspect and clone https://example.com/"))
        self.assertIsNone(simple_clone_target("Clone https://example.com/ and change its heading"))
        with patch.object(self.d, "dispatch", return_value={
            "decision": {"verdict": "allow"}, "ok": True, "output": {"index": "index.html"},
        }) as dispatch, contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(run_static_clone(self.d, "https://example.com/"))
        dispatch.assert_called_once_with("clone_page", {"url": "https://example.com/"})

    def test_policy_error_fails_closed(self):
        with patch("webcloner.policy.Policy.evaluate", side_effect=RuntimeError(SECRET)), patch.object(self.d, "_execute") as execute:
            result = self.d.dispatch("list_files", {"directory": "."})
            self.assertFalse(result["ok"])
            execute.assert_not_called()
            self.assertNotIn(SECRET, json.dumps(result))

    def test_audit_failure_prevents_execution(self):
        with patch.object(self.d.audit, "emit", side_effect=OSError("disk full")), patch.object(self.d, "_execute") as execute:
            with self.assertRaises(OSError):
                self.d.dispatch("write_file", {"filename": "x", "content": "x"})
            execute.assert_not_called()

    def test_approval_missing_and_granted(self):
        self.approval_policy()
        args = {"filename": "index.html", "content": "hello"}
        self.assertFalse(self.d.dispatch("write_file", args)["ok"])
        self.d.approval_ui = lambda request, decision: True
        self.assertTrue(self.d.dispatch("write_file", args)["ok"])
        events = [e["event"] for e in self.events()]
        self.assertIn("approval.denied", events)
        self.assertIn("approval.consumed", events)

    def test_approval_expiry_replay_binding(self):
        r = ToolRequest.parse("write_file", {"filename": "index.html", "content": "hello"})
        approvals = self.d.approvals
        token = approvals.issue(r, "v1")
        self.assertTrue(approvals.consume(token, r, "v1"))
        self.assertFalse(approvals.consume(token, r, "v1"))
        token = approvals.issue(r, "v1", ttl=-1)
        self.assertFalse(approvals.consume(token, r, "v1"))
        for changed, version in ((replace(r, action="read_file"), "v1"), (replace(r, arguments_json='{"filename":"other"}'), "v1"), (r, "v2")):
            token = approvals.issue(r, "v1")
            self.assertFalse(approvals.consume(token, changed, version))
        self.assertFalse(approvals.consume("model-supplied-token", r, "v1"))

    def test_policy_change_while_approving(self):
        self.approval_policy()
        def change(request, decision):
            data = json.loads(self.policy_path.read_text())
            data["version"] = "new"
            self.policy_path.write_text(json.dumps(data))
            return True
        self.d.approval_ui = change
        self.assertFalse(self.d.dispatch("write_file", {"filename": "x", "content": "x"})["ok"])
        self.assertFalse((self.base / "output/x").exists())

    def test_protected_configuration(self):
        with self.assertRaises(ValueError):
            Dispatcher(self.base / "output", self.base / "output/policy.json", self.base / "audit.jsonl")
        with self.assertRaises(ValueError):
            Dispatcher(self.base / "output", self.policy_path, self.base / "output/events.jsonl")
        self.assertFalse(self.d.dispatch("write_file", {"filename": "../policy.json", "content": "{}"})["ok"])

    def test_secrets_output_exceptions_logs(self):
        private = "-----BEGIN PRIVATE KEY-----\nSYNTHETIC_PRIVATE_MATERIAL\n-----END PRIVATE KEY-----"
        self.d.workspace.write("secret.txt", (SECRET + "\n" + private + "\napi_key=syntheticValue").encode())
        result = self.d.dispatch("read_file", {"filename": "secret.txt"})
        with patch.object(self.d, "_execute", side_effect=RuntimeError(SECRET + "\n" + private)):
            error = self.d.dispatch("list_files", {"directory": "."})
        blob = json.dumps(result) + json.dumps(error) + (self.base / "events.jsonl").read_text()
        for raw in (SECRET, "SYNTHETIC_PRIVATE_MATERIAL", "syntheticValue"):
            self.assertNotIn(raw, blob)
        self.assertIn("[REDACTED]", blob)

    def test_injection_recording_is_blocked(self):
        self.d.fetcher = FixtureTransport()
        (self.base / "synthetic-secret.txt").write_text(SECRET)
        responses = iter(json.loads((FIXTURES / "injection-recording.json").read_text()))
        with contextlib.redirect_stdout(io.StringIO()) as console:
            self.assertTrue(run_loop(self.d, lambda _: json.dumps(next(responses)), "Clone malicious fixture"))
        verdicts = [e["decision"]["verdict"] for e in self.events() if e["event"] == "intent"]
        self.assertEqual(verdicts, ["allow", "deny", "deny", "deny"])
        self.assertNotIn(SECRET, console.getvalue() + (self.base / "events.jsonl").read_text())

    def test_process_disabled_by_default(self):
        self.assertEqual(self.d.dispatch("execute_command", {"job": "validate_html", "filename": "index.html"})["decision"]["verdict"], "deny")

    def test_strict_json_with_braces_in_strings(self):
        self.assertEqual(extract_first_json('{"step":"OUTPUT","content":"brace }"}')["content"], "brace }")
        for raw in ('{} {}', '[]', '{"step":"TOOL","approval":true}', 'not json'):
            with self.assertRaises(ValueError):
                extract_first_json(raw)

    def test_known_tool_shorthand_is_normalized(self):
        parsed = extract_first_json('{"step":"LIST_FILES","directory":"."}')
        self.assertEqual(parsed["step"], "TOOL")
        self.assertEqual(parsed["tool_name"], "list_files")
        self.assertEqual(parsed["tool_args"], {"directory": "."})
        with self.assertRaises(ValueError):
            extract_first_json('{"step":"DELETE_FILES","directory":"."}')

    def test_think_adds_continue_message(self):
        snapshots = []
        responses = iter([
            '{"step":"THINK","content":"Inspecting"}',
            '{"step":"OUTPUT","content":"Finished"}',
        ])
        def respond(messages):
            snapshots.append([dict(message) for message in messages])
            return next(responses)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(run_loop(self.d, respond, "fixture"))
        self.assertEqual(snapshots[1][-1]["role"], "user")
        self.assertIn("Continue now", snapshots[1][-1]["content"])

    def test_invalid_model_json_retries(self):
        responses = iter(["", "not json", '{"step":"OUTPUT","content":"Recovered"}'])
        with contextlib.redirect_stdout(io.StringIO()) as console:
            self.assertTrue(run_loop(self.d, lambda _: next(responses), "fixture"))
        self.assertIn("Recovered", console.getvalue())


if __name__ == "__main__":
    unittest.main()
