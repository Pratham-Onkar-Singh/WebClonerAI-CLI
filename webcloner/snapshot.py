"""Bounded static page snapshot using only the constrained fetcher/workspace."""
import hashlib
import json
import posixpath
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

MAX_RESOURCES = 160
MAX_TOTAL_BYTES = 30_000_000
MAX_DOWNLOAD_WORKERS = 8
MAX_STREAM_BOUNDARIES = 32


class Resources(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.stylesheets = []
        self.media = []
        self.in_style = False

    @staticmethod
    def add(values, base_url, value):
        if not value or value.startswith(("data:", "blob:", "javascript:", "#")):
            return
        absolute = urljoin(base_url, value)
        if absolute not in values:
            values.append(absolute)

    def handle_starttag(self, tag, attrs):
        data = {key.lower(): value or "" for key, value in attrs}
        if tag == "link" and "stylesheet" in data.get("rel", "").lower():
            self.add(self.stylesheets, self.base_url, data.get("href"))
        if tag in ("img", "source"):
            self.add(self.media, self.base_url, data.get("src"))
            for candidate in data.get("srcset", "").split(","):
                self.add(self.media, self.base_url, candidate.strip().split(" ")[0])
        if tag == "video":
            self.add(self.media, self.base_url, data.get("poster"))
        self.add_css(data.get("style", ""))
        if tag == "style":
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.add_css(data)

    def add_css(self, css):
        imports = {urljoin(self.base_url, match.group("url").strip()) for match in CSS_IMPORT.finditer(css)}
        for imported in imports:
            self.add(self.stylesheets, self.base_url, imported)
        for match in CSS_URL.finditer(css):
            value = match.group("url").strip()
            absolute = urljoin(self.base_url, value)
            if absolute not in imports:
                self.add(self.media, self.base_url, value)


def safe_name(url, kind):
    path = unquote(urlsplit(url).path)
    basename = PurePosixPath(path).name or ("style.css" if kind == "styles" else "resource.bin")
    basename = re.sub(r"[^A-Za-z0-9_.-]", "-", basename)[:80].strip(".-") or "resource.bin"
    if kind == "styles" and not basename.lower().endswith(".css"):
        basename += ".css"
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    return f"assets/{kind}/{digest}-{basename}"


STREAM_BOUNDARY = re.compile(
    r"<!--\$\?-->\s*<template\b[^>]*\bid=(?P<quote>['\"])B:(?P<identifier>[A-Za-z0-9:_-]+)(?P=quote)[^>]*>\s*</template>",
    re.I,
)
DIV_TOKEN = re.compile(r"<!--.*?-->|</?div\b[^>]*>", re.I | re.S)


def matching_div_end(html, opening_end):
    """Return the closing-tag span for a div that starts before opening_end."""
    depth = 1
    for token in DIV_TOKEN.finditer(html, opening_end):
        value = token.group(0)
        if value.startswith("<!--"):
            continue
        if re.match(r"</div\b", value, re.I):
            depth -= 1
            if depth == 0:
                return token.start(), token.end()
        elif not value.rstrip().endswith("/>"):
            depth += 1
    return None


def unwrap_react_streaming(html):
    """Apply React's server-streamed fallback replacement without executing JS.

    React/Next.js sends a visible fallback, followed by a hidden ``S:<id>`` div.
    Its hydration script normally replaces the fallback with that div's children.
    Static snapshots intentionally remove that script, so reproduce only this
    markup move when the complete server-rendered content is already present.
    """
    count = 0
    search_from = 0
    while count < MAX_STREAM_BOUNDARIES:
        boundary = STREAM_BOUNDARY.search(html, search_from)
        if boundary is None:
            break
        fallback_end = html.find("<!--/$-->", boundary.end())
        if fallback_end < 0:
            search_from = boundary.end()
            continue
        identifier = re.escape(boundary.group("identifier"))
        hidden = re.compile(
            rf"<div\b(?=[^>]*\sid=(['\"])S:{identifier}\1)(?=[^>]*\shidden(?:\s|=|/?>))[^>]*>",
            re.I,
        ).search(html, fallback_end + len("<!--/$-->"))
        if hidden is None:
            search_from = fallback_end + len("<!--/$-->")
            continue
        closing = matching_div_end(html, hidden.end())
        if closing is None:
            search_from = hidden.end()
            continue
        close_start, close_end = closing
        html = html[:boundary.start()] + html[hidden.end():close_start] + html[close_end:]
        count += 1
        search_from = boundary.start()
    return html, count


def sanitize_html(html):
    # This creates a static preview. It is scoped sanitization, not a general HTML sanitizer.
    html = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", html, flags=re.I | re.S)
    html = re.sub(r"</?script\b[^>]*>", "", html, flags=re.I | re.S)
    html = re.sub(r"<link\b(?=[^>]*(?:rel\s*=\s*['\"]?modulepreload|as\s*=\s*['\"]?script))[^>]*>", "", html, flags=re.I)
    html = re.sub(r"<(?:iframe|object|embed)\b[^>]*>.*?</(?:iframe|object|embed)\s*>", "", html, flags=re.I | re.S)
    html = re.sub(r"<(?:iframe|object|embed)\b[^>]*?/?>", "", html, flags=re.I | re.S)
    html = re.sub(r"<base\b[^>]*>", "", html, flags=re.I)
    html = re.sub(r"<meta\b[^>]*http-equiv\s*=\s*(['\"]?)content-security-policy\1[^>]*>", "", html, flags=re.I)
    html = re.sub(r"\s+on[a-z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.I)
    html = re.sub(r"\s+srcdoc\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.I)
    html = re.sub(r"((?:href|src|action)\s*=\s*['\"])\s*javascript:[^'\"]*(['\"])", r"\1#\2", html, flags=re.I)
    html = re.sub(r"((?:href|src|action)\s*=\s*)javascript:[^\s>]+", r"\1#", html, flags=re.I)
    marker = "<!-- Static WebCloner snapshot: active scripts removed. -->"
    return html.replace("<head>", "<head>" + marker, 1) if "<head>" in html else marker + html


def rewrite_html_urls(html, base_url, mapping):
    attr = re.compile(r"(?P<prefix>\b(?:src|href|poster)\s*=\s*)(?P<quote>['\"])(?P<url>.*?)(?P=quote)", re.I | re.S)
    def replace(match):
        value = match.group("url")
        local = mapping.get(urljoin(base_url, value))
        return match.group("prefix") + match.group("quote") + (local or value) + match.group("quote")
    html = attr.sub(replace, html)
    srcset = re.compile(r"(?P<prefix>\bsrcset\s*=\s*)(?P<quote>['\"])(?P<value>.*?)(?P=quote)", re.I | re.S)
    def replace_srcset(match):
        candidates = []
        for item in match.group("value").split(","):
            pieces = item.strip().split()
            if pieces:
                pieces[0] = mapping.get(urljoin(base_url, pieces[0]), pieces[0])
            candidates.append(" ".join(pieces))
        return match.group("prefix") + match.group("quote") + ", ".join(candidates) + match.group("quote")
    return srcset.sub(replace_srcset, html)


CSS_URL = re.compile(r"url\(\s*(?P<quote>['\"]?)(?P<url>[^)'\"]+)(?P=quote)\s*\)", re.I)
CSS_IMPORT = re.compile(r"@import\s+(?:url\(\s*)?(?P<quote>['\"]?)(?P<url>[^)'\"\s;]+)(?P=quote)\s*\)?", re.I)


def rewrite_css_urls(css, base_url, mapping, relative_to=""):
    def target(value):
        local = mapping.get(urljoin(base_url, value.strip()))
        return posixpath.relpath(local, relative_to) if local and relative_to else local

    def replace_url(match):
        local = target(match.group("url"))
        return f"url('{local}')" if local else match.group(0)

    css = CSS_URL.sub(replace_url, css)
    def replace_import(match):
        local = target(match.group("url"))
        return f"@import '{local}'" if local else match.group(0)
    return CSS_IMPORT.sub(replace_import, css)


def rewrite_inline_css(html, base_url, mapping):
    blocks = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.I | re.S)
    html = blocks.sub(lambda match: match.group(1) + rewrite_css_urls(match.group(2), base_url, mapping) + match.group(3), html)
    attributes = re.compile(r"(?P<prefix>\bstyle\s*=\s*)(?P<quote>['\"])(?P<css>.*?)(?P=quote)", re.I | re.S)
    return attributes.sub(lambda match: match.group("prefix") + match.group("quote") +
                          rewrite_css_urls(match.group("css"), base_url, mapping) + match.group("quote"), html)


class StaticPageCloner:
    def __init__(self, fetcher, workspace):
        self.fetcher = fetcher
        self.workspace = workspace
        self.mapping = {}
        self.failures = []
        self.total_bytes = 0
        self.resource_count = 0
        self.byte_limit_reached = False
        self.lock = threading.Lock()

    def fetch(self, url):
        with self.lock:
            if self.byte_limit_reached:
                raise ValueError("Static snapshot total byte limit reached")
        data = self.fetcher.fetch(url)
        with self.lock:
            if self.total_bytes + len(data) > MAX_TOTAL_BYTES:
                self.byte_limit_reached = True
                raise ValueError("Static snapshot total byte limit reached")
            self.total_bytes += len(data)
        return data

    def reserve(self, url, kind):
        """Reserve one bounded output name and identify the first downloader."""
        with self.lock:
            if url in self.mapping:
                return self.mapping[url], False
            if self.resource_count >= MAX_RESOURCES:
                raise ValueError("Static snapshot resource limit reached")
            local = safe_name(url, kind)
            self.mapping[url] = local
            self.resource_count += 1
            return local, True

    def failed(self, url, local, exc):
        with self.lock:
            if self.mapping.get(url) == local:
                self.mapping.pop(url, None)
            self.failures.append({"url": url[:500], "reason": str(exc)[:300]})

    def download_media(self, url):
        try:
            local, owner = self.reserve(url, "media")
            if not owner:
                return local
            data = self.fetch(url)
            self.workspace.write(local, data)
            return local
        except Exception as exc:
            self.failed(url, locals().get("local"), exc)
            return None

    def download_stylesheet(self, url, depth=0):
        try:
            # Reserving before following imports also breaks import cycles.
            local, owner = self.reserve(url, "styles")
            if not owner:
                return local
            css = self.fetch(url).decode("utf-8", errors="replace")
            referenced = [match.group("url").strip() for match in CSS_URL.finditer(css)]
            imports = {urljoin(url, match.group("url").strip()) for match in CSS_IMPORT.finditer(css)}
            if depth < 2:
                for imported in sorted(imports):
                    self.download_stylesheet(imported, depth + 1)
            media = []
            for value in referenced:
                absolute = urljoin(url, value)
                if not value.startswith(("data:", "blob:", "#")) and absolute not in imports and absolute not in media:
                    media.append(absolute)
            # TLS setup dominates large pages. Bounded parallel downloads keep a
            # real snapshot from taking several minutes without increasing scope.
            with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as executor:
                list(executor.map(self.download_media, media))
            css = rewrite_css_urls(css, url, self.mapping, posixpath.dirname(local))
            self.workspace.write(local, css.encode())
            return local
        except Exception as exc:
            self.failed(url, locals().get("local"), exc)
            return None

    def clone(self, url):
        source = self.fetcher.fetch(url)
        self.total_bytes = len(source)
        html = source.decode("utf-8", errors="replace")
        html, streaming_boundaries = unwrap_react_streaming(html)
        resources = Resources(url)
        resources.feed(html)
        resources.close()
        for stylesheet in resources.stylesheets[:MAX_RESOURCES]:
            self.download_stylesheet(stylesheet)
        with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as executor:
            list(executor.map(self.download_media, resources.media[:MAX_RESOURCES]))
        output = rewrite_html_urls(sanitize_html(html), url, self.mapping)
        output = rewrite_inline_css(output, url, self.mapping)
        self.workspace.write("index.html", output.encode())
        self.workspace.write("snapshot.json", json.dumps({
            "source_url": url,
            "mode": "static_server_rendered_snapshot",
            "scripts_removed": True,
            "react_streaming_boundaries_unwrapped": streaming_boundaries,
            "source_bytes": len(source),
            "localized_resources": len(self.mapping),
            "attempted_resources": self.resource_count,
            "download_failures": self.failures[:50],
        }, indent=2).encode())
        return {"index": "index.html", "source_bytes": len(source), "localized_resources": len(self.mapping),
                "attempted_resources": self.resource_count,
                "download_failures": len(self.failures), "scripts_removed": True,
                "react_streaming_boundaries_unwrapped": streaming_boundaries}
