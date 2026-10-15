"""SSRF-safe HTTP fetching (threat model T2).

Defences, all enforced in code outside any model prompt:
- only http/https, default ports, no credentials in URLs;
- DNS is resolved by us and *every* resolved address must be public (blocks loopback,
  private, link-local incl. cloud metadata 169.254.169.254, CGNAT, multicast, reserved,
  IPv4-mapped IPv6 tricks); the connection is then pinned to a vetted address, so a second
  DNS answer (rebinding) cannot redirect it; TLS still verifies the original hostname;
- redirects are followed manually and every hop is re-validated;
- response size, time, and content type are bounded; cookies and env proxies are ignored.

When an egress proxy is mandatory, the proxy must enforce the same policy (documented in the
threat model); this fetcher refuses to run through one silently.
"""

import ipaddress
import socket
import ssl
import typing
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import certifi
import httpcore
import httpx

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], list[str]]

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
ALLOWED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain", "application/pdf"})


def is_public_ip(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_ip(ip.ipv4_mapped)
        if ip.sixtofour is not None or ip.teredo is not None:
            return False
    return ip.is_global and not ip.is_multicast


class FetchError(Exception):
    """A fetch that did not produce a readable document. `reason` is a short, loggable code."""

    def __init__(self, reason: str, *, transient: bool = False, retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.transient = transient
        self.retry_after = retry_after


@dataclass(frozen=True)
class FetchPolicy:
    max_bytes: int = 2_000_000
    timeout_seconds: float = 10.0
    max_redirects: int = 3
    allowed_ports: frozenset[int] = frozenset({80, 443})
    allowed_content_types: frozenset[str] = ALLOWED_CONTENT_TYPES
    allow_ip: Callable[[IPAddress], bool] = field(default=is_public_ip)


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    content_type: str
    charset: str | None
    body: bytes
    redirects: tuple[str, ...]


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError("dns_failed", transient=True) from exc
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


class _PinnedBackend(httpcore.NetworkBackend):
    def __init__(self, resolver: Resolver, policy: FetchPolicy) -> None:
        self._resolver = resolver
        self._policy = policy
        self._inner = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        addresses = self._resolver(host, port)
        if not addresses:
            raise FetchError("dns_failed", transient=True)
        for address in addresses:
            if not self._policy.allow_ip(ipaddress.ip_address(address.split("%")[0])):
                raise FetchError("blocked_address")
        return self._inner.connect_tcp(addresses[0], port, timeout, local_address, socket_options)

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        raise FetchError("blocked_address")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


class _PinnedTransport(httpx.HTTPTransport):
    """httpx transport whose connection pool uses the pinned network backend.

    httpx 0.28 exposes no public hook for a custom network backend, so the pool built by
    HTTPTransport is replaced. Pinned dependency: tests/test_fetcher.py must pass on upgrade."""

    def __init__(self, backend: httpcore.NetworkBackend) -> None:
        super().__init__(trust_env=False, retries=0)
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(cafile=certifi.where()),
            max_connections=10,
            max_keepalive_connections=0,
            network_backend=backend,
        )


def validate_url(url: str, policy: FetchPolicy) -> None:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise FetchError("invalid_url") from exc
    if parts.scheme not in ("http", "https"):
        raise FetchError("blocked_scheme")
    if not parts.hostname:
        raise FetchError("invalid_url")
    if parts.username or parts.password:
        raise FetchError("credentials_in_url")
    effective_port = port or (443 if parts.scheme == "https" else 80)
    if effective_port not in policy.allowed_ports:
        raise FetchError("blocked_port")


class SafeFetcher:
    def __init__(
        self,
        policy: FetchPolicy | None = None,
        resolver: Resolver = system_resolver,
        user_agent: str = "AgentOrchestrationSystem/0.5 (+research; respects robots policies)",
    ) -> None:
        self.policy = policy or FetchPolicy()
        self._client = httpx.Client(
            transport=_PinnedTransport(_PinnedBackend(resolver, self.policy)),
            follow_redirects=False,
            timeout=self.policy.timeout_seconds,
            trust_env=False,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain,application/pdf",
            },
        )

    def close(self) -> None:
        self._client.close()

    def fetch(self, url: str) -> FetchResult:
        redirects: list[str] = []
        current = url
        for _ in range(self.policy.max_redirects + 1):
            validate_url(current, self.policy)
            try:
                with self._client.stream("GET", current) as response:
                    if response.status_code in REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("redirect_without_location")
                        redirects.append(current)
                        current = urljoin(current, location)
                        continue
                    return self._read(current, response, tuple(redirects))
            except httpx.TimeoutException as exc:
                raise FetchError("timeout", transient=True) from exc
            except httpx.TransportError as exc:
                raise FetchError("connect_failed", transient=True) from exc
        raise FetchError("too_many_redirects")

    def _read(self, url: str, response: httpx.Response, redirects: tuple[str, ...]) -> FetchResult:
        status = response.status_code
        if status == 429 or status >= 500:
            retry_after = response.headers.get("retry-after", "")
            raise FetchError(
                f"http_{status}",
                transient=True,
                retry_after=float(retry_after) if retry_after.isdigit() else None,
            )
        if status >= 400:
            raise FetchError(f"http_{status}")
        content_type, _, params = response.headers.get("content-type", "").partition(";")
        content_type = content_type.strip().lower()
        if content_type not in self.policy.allowed_content_types:
            raise FetchError("unsupported_content_type")
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self.policy.max_bytes:
            raise FetchError("too_large")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > self.policy.max_bytes:
                raise FetchError("too_large")
            chunks.append(chunk)
        charset = None
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.lower() == "charset" and value:
                charset = value.strip("\"'").lower()
        return FetchResult(url, status, content_type, charset, b"".join(chunks), redirects)


class Fetcher(typing.Protocol):
    def fetch(self, url: str) -> FetchResult: ...
