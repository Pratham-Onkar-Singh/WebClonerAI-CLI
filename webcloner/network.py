"""Explicit HTTPS fetches: exact host allowlist, public IPs, pinned TLS connections."""
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from .files import MAX_BYTES


def public_ip(address):
    ip = ipaddress.ip_address(address)
    if not ip.is_global or ip.is_multicast or ip.is_unspecified or getattr(ip, "ipv4_mapped", None):
        raise ValueError("Destination must be a public unicast IP")
    if ip.version == 4 and ip in ipaddress.ip_network("192.0.0.0/24"):
        # Classification of this special-use block differs across Python versions.
        raise ValueError("IPv4 protocol-assignment addresses are unsupported")
    if ip.version == 6 and (
        ip not in ipaddress.ip_network("2000::/3")
        or ip.sixtofour is not None
        or ip.teredo is not None
        or ip.scope_id is not None
    ):
        # Fail closed on transition/translation and scoped addresses; an embedded
        # private IPv4 destination must not bypass the public-address check.
        raise ValueError("Only native, unscoped global-unicast IPv6 is supported")
    return ip


def normalize_url(url, hosts):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in url) or "\\" in url:
        raise ValueError("Invalid URL")
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443) or p.fragment:
        raise ValueError("Only HTTPS URLs on port 443 without credentials or fragments are supported")
    host = p.hostname.lower()
    if host not in hosts:
        raise ValueError("Destination is not in the exact host allowlist")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or host.endswith("."):
            raise ValueError("Invalid DNS name")
    else:
        public_ip(host)
    return urlunsplit(("https", p.netloc.lower(), p.path or "/", p.query, ""))


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        ip = public_ip(self.address)
        # Numeric socket address: no second DNS lookup. TLS still verifies original hostname.
        raw = socket.socket(socket.AF_INET6 if ip.version == 6 else socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(self.timeout)
        try:
            raw.connect((str(ip), 443))
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class Fetcher:
    def __init__(self, hosts, resolver=socket.getaddrinfo, connection=PinnedHTTPS):
        self.hosts = hosts
        self.resolver = resolver
        self.connection = connection

    def fetch(self, url):
        deadline = time.monotonic() + 15
        for _ in range(4):
            url = normalize_url(url, self.hosts)
            p = urlsplit(url)
            addresses = {row[4][0] for row in self.resolver(p.hostname, 443, type=socket.SOCK_STREAM)}
            if not addresses:
                raise ValueError("DNS returned no addresses")
            for address in addresses:
                public_ip(address)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Fetch deadline exceeded")
            connection = self.connection(p.hostname, sorted(addresses)[0], min(remaining, 5))
            def interrupt_connection(connection=connection):
                try:
                    if connection.sock:
                        connection.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
            # A wall deadline also interrupts slow-drip HTTP headers/body reads.
            timer = threading.Timer(remaining, interrupt_connection)
            timer.daemon = True
            timer.start()
            try:
                connection.request("GET", p.path + (("?" + p.query) if p.query else ""), headers={"User-Agent": "WebCloner/1", "Accept-Encoding": "identity"})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location:
                        raise ValueError("Redirect without Location")
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise ValueError(f"HTTP status {response.status}")
                if response.getheader("Content-Encoding", "identity") != "identity":
                    raise ValueError("Compressed responses are unsupported")
                data = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Fetch deadline exceeded")
                    if connection.sock:
                        connection.sock.settimeout(min(remaining, 5))
                    chunk = response.read1(min(65536, MAX_BYTES + 1 - len(data)))
                    if not chunk:
                        return bytes(data)
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError("Response exceeds byte limit")
            finally:
                timer.cancel()
                connection.close()
        raise ValueError("Redirect limit exceeded")
