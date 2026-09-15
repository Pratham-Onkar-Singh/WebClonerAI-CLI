"""Offline clone: local fixture, recorded model responses, mocked transport."""
import argparse
import json
from pathlib import Path

from agent import ROOT, run_loop
from .dispatcher import Dispatcher

FIXTURES = ROOT / "tests/fixtures/v1"


class FixtureTransport:
    # Operator/test-only injection; not available as a model tool or live CLI flag.
    def fetch(self, url):
        files = {"https://example.com/": "site.html", "https://example.com/styles.css": "styles.css",
                 "https://example.com/malicious": "malicious.html"}
        return (FIXTURES / files[url]).read_bytes()


def recording():
    return [
        {"step": "TOOL", "tool_name": "fetch_url", "tool_args": {"url": "https://example.com/"}},
        {"step": "TOOL", "tool_name": "write_file", "tool_args": {"filename": "index.html", "content": (FIXTURES / "site.html").read_text()}},
        {"step": "TOOL", "tool_name": "download_asset", "tool_args": {"filename": "styles.css", "url": "https://example.com/styles.css"}},
        {"step": "TOOL", "tool_name": "read_file", "tool_args": {"filename": "index.html"}},
        {"step": "TOOL", "tool_name": "list_files", "tool_args": {"directory": "."}},
        {"step": "OUTPUT", "content": "Recorded fixture clone complete: index.html and styles.css."},
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "demo_output")
    args = parser.parse_args()
    dispatcher = Dispatcher(args.output, ROOT / "policies/default.json", ROOT / ".webcloner/demo-events.jsonl")
    dispatcher.fetcher = FixtureTransport()
    try:
        responses = iter(recording())
        if not run_loop(dispatcher, lambda messages: json.dumps(next(responses)), "Clone the local Orbit fixture"):
            raise RuntimeError("Recorded loop failed")
        assert (args.output / "index.html").read_bytes() == (FIXTURES / "site.html").read_bytes()
        assert (args.output / "styles.css").read_bytes() == (FIXTURES / "styles.css").read_bytes()
        print("Verified fixture bytes. Mode: recorded model responses + mocked network; no isolation claim.")
    finally:
        dispatcher.close()


if __name__ == "__main__":
    main()
