import re
from urllib.parse import urlsplit, urlunsplit

_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----.*?(?:-----END (?:[A-Z]+ )?PRIVATE KEY-----|$)", re.S),
    re.compile(r"\b(?:sk-|hf_)[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*[^\s,;\"']+"),
)
_HTTPS_URL = re.compile(r"https://[^\s'\"<>]+")


def redact_url_queries(value):
    def replace(match):
        parsed = urlsplit(match.group(0))
        if not parsed.query:
            return match.group(0)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "[REDACTED_QUERY]", ""))
    return _HTTPS_URL.sub(replace, value)


def redact(value):
    if isinstance(value, str):
        value = redact_url_queries(value)
        for pattern in _PATTERNS:
            value = pattern.sub("[REDACTED]", value)
        return value
    if isinstance(value, dict):
        return {redact(str(k)): redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value
