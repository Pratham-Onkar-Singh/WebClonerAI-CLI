import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from webcloner.files import Workspace
from webcloner.snapshot import StaticPageCloner, sanitize_html, unwrap_react_streaming


class FixtureFetcher:
    def __init__(self):
        self.calls = []
        self.content = {
            "https://example.com/": b'''<!doctype html><html><head><link rel="stylesheet" href="/app.css"><link rel="modulepreload" href="/module.js"><style>.inline{background:url('/inline.webp')}</style><script src="/app.js"></script><script src="/orphan.js"/></head><body onload="bad()"><a href=javascript:bad()>bad</a><img src="/hero.png"><h1 class="hero" style="background:url('/inline.webp')">Real heading</h1></body></html>''',
            "https://example.com/app.css": b"@import url('/nested.css'); @font-face{src:url('/font.woff2')} .hero{color:#123456;background:url('/bg.webp')}",
            "https://example.com/nested.css": b".nested{display:grid}",
            "https://example.com/hero.png": b"PNG fixture",
            "https://example.com/font.woff2": b"FONT fixture",
            "https://example.com/bg.webp": b"WEBP fixture",
            "https://example.com/inline.webp": b"INLINE fixture",
        }

    def fetch(self, url):
        self.calls.append(url)
        return self.content[url]


class SnapshotTests(unittest.TestCase):
    def test_react_streaming_fallback_is_replaced_without_running_scripts(self):
        source = '''<html><body><!--$?--><template id="B:0"></template><div class="loader">Loading</div><!--/$--><div hidden id="S:0"><style>.page{display:block}</style><main class="page"><div>Actual page</div></main></div><script>$RC("B:0","S:0")</script></body></html>'''
        unwrapped, count = unwrap_react_streaming(source)
        output = sanitize_html(unwrapped)
        self.assertEqual(count, 1)
        self.assertIn("Actual page", output)
        self.assertNotIn("Loading", output)
        self.assertNotIn('id="S:0"', output)
        self.assertNotIn("<script", output)

    def test_static_clone_preserves_real_css_and_localizes_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace(Path(temporary) / "output")
            try:
                fetcher = FixtureFetcher()
                result = StaticPageCloner(fetcher, workspace).clone("https://example.com/")
                html = workspace.read("index.html").decode()
                manifest = json.loads(workspace.read("snapshot.json"))
                self.assertEqual(result["localized_resources"], 6)
                self.assertEqual(manifest["download_failures"], [])
                self.assertNotIn("<script", html)
                self.assertNotIn("modulepreload", html)
                self.assertNotIn("javascript:", html)
                self.assertNotIn("onload", html)
                self.assertNotIn("https://example.com/app.css", html)
                self.assertIn("assets/styles/", html)
                self.assertIn("assets/media/", html)
                self.assertNotIn("url('/inline.webp')", html)
                styles = [workspace.read("assets/styles/" + name).decode()
                          for name in workspace.list("assets/styles") if name.endswith(".css")]
                css = next(value for value in styles if ".hero" in value)
                self.assertIn("../media/", css)
                self.assertIn("color:#123456", css)
                self.assertNotIn("url('/nested.css')", css)
                self.assertNotIn("url('/font.woff2')", css)
            finally:
                workspace.close()

    def test_resource_attempts_are_bounded_even_when_downloads_fail(self):
        class AnyFetcher:
            def __init__(self):
                self.calls = []
            def fetch(self, url):
                self.calls.append(url)
                if url == "https://example.com/":
                    return b'<html><body><img src="/1"><img src="/2"><img src="/3"><img src="/4"></body></html>'
                return b"asset"

        with tempfile.TemporaryDirectory() as temporary, patch("webcloner.snapshot.MAX_RESOURCES", 2):
            workspace = Workspace(Path(temporary) / "output")
            try:
                fetcher = AnyFetcher()
                result = StaticPageCloner(fetcher, workspace).clone("https://example.com/")
                self.assertEqual(result["attempted_resources"], 2)
                self.assertEqual(result["localized_resources"], 2)
                self.assertEqual(len(fetcher.calls), 3)  # page plus two resources
            finally:
                workspace.close()

    def test_failed_resource_does_not_prevent_html_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace(Path(temporary) / "output")
            try:
                fetcher = FixtureFetcher()
                del fetcher.content["https://example.com/hero.png"]
                result = StaticPageCloner(fetcher, workspace).clone("https://example.com/")
                self.assertEqual(result["download_failures"], 1)
                self.assertIn("/hero.png", workspace.read("index.html").decode())
            finally:
                workspace.close()
