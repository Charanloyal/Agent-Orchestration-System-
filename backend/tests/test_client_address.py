"""G3 (ADR 0025): the rate-limit client address cannot be chosen by the client.

Uvicorn no longer trusts forwarded headers. The app reads `X-Forwarded-For` only as far as
AOS_TRUSTED_PROXY_HOPS says: entries appended by trusted proxies are counted from the right,
so anything the client wrote on the left is never used.
"""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.config import Settings
from app.db.models import RateLimitCounter
from app.services.ratelimit import client_address


def request(peer: str, *forwarded: str) -> Request:
    headers = [(b"x-forwarded-for", value.encode()) for value in forwarded]
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


@pytest.mark.parametrize(
    ("hops", "forwarded", "expected"),
    [
        (0, ("6.6.6.6",), "10.0.0.1"),  # no trusted proxy: the socket peer, header ignored
        (1, ("203.0.113.7",), "203.0.113.7"),  # the proxy appended the real client
        (1, ("6.6.6.6, 203.0.113.7",), "203.0.113.7"),  # a client-written entry on the left
        (1, ("6.6.6.6", "203.0.113.7"), "203.0.113.7"),  # repeated headers form one list
        (2, ("6.6.6.6, 203.0.113.7, 198.51.100.2",), "203.0.113.7"),  # two trusted proxies
        (1, (), "10.0.0.1"),  # header missing: fall back to the peer
        (2, ("203.0.113.7",), "10.0.0.1"),  # fewer entries than trusted hops: not trusted
        (1, (" , ",), "10.0.0.1"),  # empty entries are ignored
    ],
)
def test_client_address_counts_trusted_hops_from_the_right(
    hops: int, forwarded: tuple[str, ...], expected: str
) -> None:
    assert client_address(request("10.0.0.1", *forwarded), hops) == expected


def test_settings_bound_the_hop_count() -> None:
    with pytest.raises(ValueError):
        Settings(trusted_proxy_hops=-1)
    with pytest.raises(ValueError):
        Settings(trusted_proxy_hops=6)


def test_rotating_a_client_supplied_forwarded_for_does_not_reset_the_login_limit(
    client: TestClient, settings_override: Callable[..., Settings], db: Session
) -> None:
    settings_override(rate_login_per_ip_5min=2, trusted_proxy_hops=1)
    places = [
        client.get(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": f"6.6.6.{n}, 203.0.113.7"},
            follow_redirects=False,
        ).headers["location"]
        for n in range(3)
    ]
    assert places[2] == "/signin?error=rate_limited", "a forged left-hand entry must not change the key"
    keys = db.scalars(select(RateLimitCounter.key).where(RateLimitCounter.key.like("login:%"))).all()
    assert len(keys) == 1 and "203.0.113.7" not in keys[0], "one hashed key; never a raw address"


def test_without_trusted_proxies_the_header_is_ignored(
    client: TestClient, settings_override: Callable[..., Settings]
) -> None:
    settings_override(rate_login_per_ip_5min=2, trusted_proxy_hops=0)
    places = [
        client.get(
            "/api/v1/auth/login", headers={"X-Forwarded-For": f"203.0.113.{n}"}, follow_redirects=False
        ).headers["location"]
        for n in range(3)
    ]
    assert places[2] == "/signin?error=rate_limited"
