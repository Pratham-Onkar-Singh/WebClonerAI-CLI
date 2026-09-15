import json
import tempfile
import unittest
from pathlib import Path

from webcloner.api import read_events


class APITests(unittest.TestCase):
    def test_redacted_filtered_bounded_events(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            lines = [json.dumps({"event": "intent", "decision": {"verdict": "deny", "action": "read_file"}, "error": "hf_SYNTHETIC123456"}) for _ in range(510)]
            path.write_text("\n".join(lines) + '\n{"partial":')
            result = read_events(path, "deny", "read_file")
            self.assertEqual(len(result), 500)
            self.assertNotIn("hf_SYNTHETIC123456", json.dumps(result))
            self.assertEqual(read_events(path, "allow"), [])
            self.assertEqual(read_events(Path(temp) / "missing"), [])

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            target = Path(temp) / "target"
            target.write_text("{}")
            path.symlink_to(target)
            with self.assertRaises(OSError):
                read_events(path)
