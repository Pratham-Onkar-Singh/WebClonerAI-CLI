import json
import unittest

from webcloner.content import MAX_MODEL_FILE_BYTES, MAX_MODEL_WEB_BYTES, compact_file_content, compact_web_content


class ContentTests(unittest.TestCase):
    def test_html_is_compacted_with_absolute_assets(self):
        html = b'''<!doctype html><html><head><title>Fixture</title>
        <link rel="stylesheet" href="/style.css"><style>body { color: red }</style>
        <script>ignored secret-sized script</script></head><body><header class="top">Brand</header>
        <h1>Hello</h1><img src="img/logo.png"><script src="/app.js"></script></body></html>'''
        result = compact_web_content(html, "https://example.com/page")
        summary = json.loads(result)
        self.assertEqual(summary["title"], "Fixture")
        self.assertIn("https://example.com/style.css", summary["stylesheet_urls"])
        self.assertIn("https://example.com/img/logo.png", summary["image_urls"])
        self.assertIn("https://example.com/app.js", summary["script_urls"])
        self.assertIn("Hello", summary["visible_text"])
        self.assertNotIn("ignored secret-sized script", result)

    def test_large_html_is_bounded(self):
        html = ("<!doctype html><html><body><main>" + "word " * 300_000 + "</main></body></html>").encode()
        result = compact_web_content(html, "https://example.com/")
        self.assertLessEqual(len(result.encode()), MAX_MODEL_WEB_BYTES)
        self.assertEqual(json.loads(result)["source_bytes"], len(html))

    def test_non_html_is_bounded(self):
        self.assertEqual(compact_web_content(b"plain text", "https://example.com/a"), "plain text")

    def test_url_query_values_do_not_enter_model_context(self):
        html = b'<html><head><link rel="stylesheet" href="/style.css?signature=private-value"></head><body><img src="/logo.png?token=private-value"></body></html>'
        result = compact_web_content(html, "https://example.com/page?token=private-value")
        self.assertNotIn("private-value", result)
        summary = json.loads(result)
        self.assertEqual(summary["source_url"], "https://example.com/page")
        self.assertEqual(summary["stylesheet_urls"], ["https://example.com/style.css"])

    def test_large_local_text_is_bounded_without_mutation(self):
        source = ("begin\n" + "middle\n" * 100_000 + "end\n").encode()
        result = compact_file_content(source, "large.css")
        summary = json.loads(result)
        self.assertEqual(summary["source_bytes"], len(source))
        self.assertEqual(summary["content_mode"], "bounded_text_preview")
        self.assertIn("begin", summary["head"])
        self.assertIn("end", summary["tail"])
        self.assertLess(len(result.encode()), MAX_MODEL_FILE_BYTES)

    def test_binary_local_file_returns_metadata(self):
        result = compact_file_content(b"\x00" * 100_000, "image.png")
        self.assertEqual(json.loads(result)["content_mode"], "binary_metadata_only")
