"""SSRF-safe fetcher against a real local HTTP server (threat model T2)."""

import ipaddress
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.tools.fetcher import FetchError, FetchPolicy, SafeFetcher, is_public_ip


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def _send(self, status: int, body: bytes = b"", content_type: str = "text/html", **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        port = self.server.server_address[1]
        routes = {
            "/page": lambda: self._send(
                200, b"<html><title>T</title><p>Hello</p></html>", "text/html; charset=utf-8"
            ),
            "/redirect-ok": lambda: self._send(302, Location="/page"),
            "/redirect-private": lambda: self._send(302, Location=f"http://internal.test:{port}/page"),
            "/redirect-metadata": lambda: self._send(302, Location="http://169.254.169.254/latest/meta-data"),
            "/redirect-loop": lambda: self._send(302, Location="/redirect-loop"),
            "/redirect-file": lambda: self._send(302, Location="file:///etc/passwd"),
            "/big": lambda: self._send(200, b"x" * 3_000_000, "text/plain"),
            "/binary": lambda: self._send(200, b"\x00\x01", "application/octet-stream"),
            "/server-error": lambda: self._send(503, b"", Retry_After="7"),
            "/missing": lambda: self._send(404),
            "/slow": lambda: (time.sleep(2), self._send(200, b"late", "text/plain")),
        }
        routes.get(self.path, lambda: self._send(404))()


@pytest.fixture(scope="module")
def server() -> Iterator[int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


HOSTS = {
    "site.test": ["127.0.0.1"],
    "internal.test": ["10.0.0.5"],
    "rebind.test": ["127.0.0.1", "192.168.1.10"],
    "metadata.test": ["169.254.169.254"],
}


def resolver(host: str, port: int) -> list[str]:
    return HOSTS.get(host, [host])


LOOPBACK = ipaddress.ip_address("127.0.0.1")


@pytest.fixture
def fetcher(server: int) -> Iterator[SafeFetcher]:
    """Policy identical to production except the test server's loopback address and port."""
    policy = FetchPolicy(
        allowed_ports=frozenset({80, 443, server}),
        timeout_seconds=1.0,
        allow_ip=lambda ip: ip == LOOPBACK or is_public_ip(ip),
    )
    instance = SafeFetcher(policy, resolver)
    yield instance
    instance.close()


def reason(fetcher: SafeFetcher, url: str) -> str:
    with pytest.raises(FetchError) as info:
        fetcher.fetch(url)
    return info.value.reason


def test_fetches_allowed_html(fetcher: SafeFetcher, server: int) -> None:
    result = fetcher.fetch(f"http://site.test:{server}/page")
    assert result.status == 200 and result.content_type == "text/html" and result.charset == "utf-8"
    assert b"Hello" in result.body


def test_follows_safe_redirects_and_records_them(fetcher: SafeFetcher, server: int) -> None:
    result = fetcher.fetch(f"http://site.test:{server}/redirect-ok")
    assert result.url.endswith("/page") and len(result.redirects) == 1


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/redirect-private", "blocked_address"),
        ("/redirect-metadata", "blocked_address"),
        ("/redirect-loop", "too_many_redirects"),
        ("/redirect-file", "blocked_scheme"),
    ],
)
def test_every_redirect_hop_is_revalidated(
    fetcher: SafeFetcher, server: int, path: str, expected: str
) -> None:
    assert reason(fetcher, f"http://site.test:{server}{path}") == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.1.2.3/",
        "http://192.168.0.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://100.64.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fd00::1]/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://internal.test/",
        "http://metadata.test/",
        "http://rebind.test/",
    ],
)
def test_private_and_special_addresses_are_blocked_before_connecting(url: str) -> None:
    production = SafeFetcher(resolver=resolver)
    assert reason(production, url) == "blocked_address"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("file:///etc/passwd", "blocked_scheme"),
        ("gopher://example.com/", "blocked_scheme"),
        ("ftp://example.com/x", "blocked_scheme"),
        ("http://user:pw@example.com/", "credentials_in_url"),
        ("http://example.com:22/", "blocked_port"),
        ("http:///nohost", "invalid_url"),
    ],
)
def test_url_shape_is_validated(url: str, expected: str) -> None:
    assert reason(SafeFetcher(resolver=resolver), url) == expected


def test_size_type_and_status_limits(fetcher: SafeFetcher, server: int) -> None:
    assert reason(fetcher, f"http://site.test:{server}/big") == "too_large"
    assert reason(fetcher, f"http://site.test:{server}/binary") == "unsupported_content_type"
    assert reason(fetcher, f"http://site.test:{server}/missing") == "http_404"
    with pytest.raises(FetchError) as info:
        fetcher.fetch(f"http://site.test:{server}/server-error")
    assert info.value.transient and info.value.retry_after == 7.0


def test_timeouts_are_transient(fetcher: SafeFetcher, server: int) -> None:
    with pytest.raises(FetchError) as info:
        fetcher.fetch(f"http://site.test:{server}/slow")
    assert info.value.reason == "timeout" and info.value.transient


def test_public_ip_classification() -> None:
    assert is_public_ip(ipaddress.ip_address("93.184.216.34"))
    assert is_public_ip(ipaddress.ip_address("2606:2800:220:1:248:1893:25c8:1946"))
    for blocked in (
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fe80::1",
        "::ffff:10.0.0.1",
        "2002:0a00:0001::1",
    ):
        assert not is_public_ip(ipaddress.ip_address(blocked)), blocked
