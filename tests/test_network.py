import io
import socket
import unittest
from unittest.mock import Mock, patch

from webcloner.network import Fetcher, PinnedHTTPS, normalize_url


def dns(addresses):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]


class Response:
    def __init__(self, status=200, body=b"fixture", headers=None):
        self.status, self.body, self.headers = status, io.BytesIO(body), headers or {}

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read1(self, size):
        return self.body.read(size)


class NetworkTests(unittest.TestCase):
    def fetcher(self, responses, addresses=None):
        connections = []
        def connect(host, address, timeout):
            connection = Mock()
            connection.getresponse.return_value = responses[len(connections)]
            connections.append((host, address, connection))
            return connection
        resolver = Mock(return_value=dns(addresses or ["93.184.216.34"]))
        return Fetcher(("example.com", "cdn.example.com"), resolver, connect), resolver, connections

    def test_success_and_pinned_address(self):
        fetcher, resolver, calls = self.fetcher([Response()])
        self.assertEqual(fetcher.fetch("https://example.com/"), b"fixture")
        self.assertEqual(calls[0][:2], ("example.com", "93.184.216.34"))
        self.assertEqual(resolver.call_count, 1)
        calls[0][2].close.assert_called_once()

    def test_disallowed_urls(self):
        for url in ("http://example.com", "file:///etc/passwd", "https://user:pass@example.com/", "https://example.com:80", "https://example.com/#x", "https://example.com\\@evil.com", "https://example.com\n", "https://evil.example.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_url(url, ("example.com",))

    def test_private_and_alternate_addresses(self):
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "192.0.0.8", "172.16.0.1", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "224.0.0.1", "0.0.0.0"):
            fetcher, _, calls = self.fetcher([Response()], [address])
            with self.subTest(address=address), self.assertRaises(ValueError):
                fetcher.fetch("https://example.com/")
            self.assertFalse(calls)
        for host in ("2130706433", "0177.0.0.1", "0x7f000001", "127.1"):
            fetcher = Fetcher((host,), Mock(return_value=dns(["127.0.0.1"])), Mock())
            with self.assertRaises(ValueError):
                fetcher.fetch("https://" + host + "/")
            fetcher.connection.assert_not_called()

    def test_mixed_dns_fails_closed(self):
        fetcher, _, calls = self.fetcher([Response()], ["93.184.216.34", "127.0.0.1"])
        with self.assertRaises(ValueError):
            fetcher.fetch("https://example.com/")
        self.assertFalse(calls)

    def test_ipv6_transition_and_scoped_addresses(self):
        for address in ("64:ff9b::7f00:1", "2002:7f00:1::", "2001::1", "2606:4700:4700::1111%eth0"):
            fetcher, _, calls = self.fetcher([Response()], [address])
            with self.subTest(address=address), self.assertRaises(ValueError):
                fetcher.fetch("https://example.com/")
            self.assertFalse(calls)

    def test_redirect_revalidates(self):
        for destination in ("http://example.com/", "https://127.0.0.1/", "https://unapproved.com/"):
            fetcher, _, calls = self.fetcher([Response(302, headers={"Location": destination})])
            with self.assertRaises(ValueError):
                fetcher.fetch("https://example.com/")
            self.assertEqual(len(calls), 1)

    def test_redirect_dns_change(self):
        fetcher, resolver, calls = self.fetcher([Response(302, headers={"Location": "/next"})])
        resolver.side_effect = [dns(["93.184.216.34"]), dns(["127.0.0.1"])]
        with self.assertRaises(ValueError):
            fetcher.fetch("https://example.com/")
        self.assertEqual(len(calls), 1)

    def test_public_ipv6(self):
        fetcher, _, calls = self.fetcher([Response()], ["2606:4700:4700::1111"])
        self.assertEqual(fetcher.fetch("https://example.com/"), b"fixture")
        self.assertEqual(calls[0][1], "2606:4700:4700::1111")

    def test_size_compression_status_redirect_limit(self):
        for responses in ([Response(body=b"x" * 1_000_001)], [Response(headers={"Content-Encoding": "gzip"})], [Response(500)], [Response(302)] , [Response(302, headers={"Location": "/again"})] * 4):
            fetcher, _, _ = self.fetcher(responses)
            with self.assertRaises(ValueError):
                fetcher.fetch("https://example.com/")

    def test_numeric_connection_does_not_resolve_again(self):
        connection = PinnedHTTPS("example.com", "93.184.216.34", 1)
        raw, context = Mock(), Mock()
        connection._context = context
        with patch("webcloner.network.socket.socket", return_value=raw), patch("webcloner.network.socket.getaddrinfo", side_effect=AssertionError("No second DNS lookup")):
            connection.connect()
        raw.connect.assert_called_once_with(("93.184.216.34", 443))
        context.wrap_socket.assert_called_once_with(raw, server_hostname="example.com")

    def test_timeout_propagates_and_closes(self):
        fetcher, _, calls = self.fetcher([Response()])
        # Error in HTTP exchange is not retried using a less restricted transport.
        original = fetcher.connection
        def failing(*args):
            connection = original(*args)
            connection.getresponse.side_effect = TimeoutError("fixture timeout")
            return connection
        fetcher.connection = failing
        with self.assertRaises(TimeoutError):
            fetcher.fetch("https://example.com/")
        calls[0][2].close.assert_called_once()
