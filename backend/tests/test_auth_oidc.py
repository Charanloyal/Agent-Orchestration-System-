"""End-to-end OIDC sign-in against the real dev issuer over HTTP, plus ID-token verification
edge cases using locally signed tokens."""

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from app.api.auth import safe_next_path
from app.auth.deps import get_oidc_client
from app.auth.oidc import OidcClient, OidcError
from app.config import Settings
from app.main import app


@pytest.fixture
def oidc_against(dev_issuer: str) -> Callable[[], OidcClient]:
    settings = Settings(oidc_issuer=dev_issuer, public_url="http://testserver", env="test")
    client = OidcClient(settings, httpx.Client(timeout=5, trust_env=False))
    app.dependency_overrides[get_oidc_client] = lambda: client
    yield lambda: client
    app.dependency_overrides.pop(get_oidc_client, None)


def sign_in_via_dev_issuer(client: TestClient, subject: str, next_path: str = "/runs") -> httpx.Response:
    start = client.get("/api/v1/auth/login", params={"next": next_path}, follow_redirects=False)
    assert start.status_code == 302
    authorize_url = start.headers["location"]
    with httpx.Client(trust_env=False) as browser:
        page = browser.get(authorize_url)
        assert page.status_code == 200
        assert "Local development sign-in" in page.text
        query = {k: v[0] for k, v in parse_qs(urlparse(authorize_url).query).items()}
        form = {
            k: query[k]
            for k in (
                "client_id",
                "redirect_uri",
                "state",
                "nonce",
                "code_challenge",
                "scope",
            )
        }
        consent = browser.post(authorize_url.split("?")[0], data={**form, "subject": subject})
    assert consent.status_code == 302
    callback = urlparse(consent.headers["location"])
    return client.get(f"{callback.path}?{callback.query}", follow_redirects=False)


def test_full_sign_in_flow_creates_session(client: TestClient, db: object, oidc_against: Any) -> None:
    response = sign_in_via_dev_issuer(client, "dev-alice")
    assert response.status_code == 302
    assert response.headers["location"] == "/runs"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "alice@example.test"
    assert body["display_name"] == "Alice Analyst"
    assert len(body["csrf_token"]) >= 32


def test_callback_state_is_single_use(client: TestClient, db: object, oidc_against: Any) -> None:
    start = client.get("/api/v1/auth/login", follow_redirects=False)
    query = {k: v[0] for k, v in parse_qs(urlparse(start.headers["location"]).query).items()}
    with httpx.Client(trust_env=False) as browser:
        consent = browser.post(
            start.headers["location"].split("?")[0],
            data={
                **{
                    k: query[k]
                    for k in (
                        "client_id",
                        "redirect_uri",
                        "state",
                        "nonce",
                        "code_challenge",
                        "scope",
                    )
                },
                "subject": "dev-bob",
            },
        )
    callback = urlparse(consent.headers["location"])
    first = client.get(f"{callback.path}?{callback.query}", follow_redirects=False)
    assert first.status_code == 302
    replay = client.get(f"{callback.path}?{callback.query}", follow_redirects=False)
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "oidc_error"


def test_unknown_state_rejected(client: TestClient, db: object, oidc_against: Any) -> None:
    response = client.get("/api/v1/auth/callback", params={"code": "x", "state": "forged"})
    assert response.status_code == 400


def test_logout_revokes_session(client: TestClient, db: object, oidc_against: Any) -> None:
    sign_in_via_dev_issuer(client, "dev-carol")
    csrf = client.get("/api/v1/auth/me").json()["csrf_token"]
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/runs/1", "/runs/1"),
        (None, "/"),
        ("https://evil.example", "/"),
        ("//evil.example", "/"),
        ("/\\evil", "/"),
        ("runs", "/"),
    ],
)
def test_next_path_prevents_open_redirect(value: str | None, expected: str) -> None:
    assert safe_next_path(value) == expected


# --- ID token verification with a locally controlled key -------------------------------------

ISSUER = "https://issuer.test"
CLIENT_ID = "aos-local"


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def verifier(signing_key: rsa.RSAPrivateKey) -> OidcClient:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)  # type: ignore[assignment]
    jwk.update({"kid": "k1", "alg": "RS256", "use": "sig"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/a",
                    "token_endpoint": f"{ISSUER}/t",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        return httpx.Response(200, json={"keys": [jwk]})

    settings = Settings(oidc_issuer=ISSUER, oidc_client_id=CLIENT_ID, env="test")
    return OidcClient(settings, httpx.Client(transport=httpx.MockTransport(handler)))


def token(key: rsa.RSAPrivateKey, **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "u1",
        "iat": now,
        "exp": now + 300,
        "nonce": "n1",
        "email": "u@example.test",
        "email_verified": True,
        "name": "U",
    }
    claims.update(overrides)
    return jwt.encode(
        {k: v for k, v in claims.items() if v is not None},
        key,
        algorithm="RS256",
        headers={"kid": "k1"},
    )


def test_valid_id_token(verifier: OidcClient, signing_key: rsa.RSAPrivateKey) -> None:
    claims = verifier.verify_id_token(token(signing_key), nonce="n1")
    assert (claims.subject, claims.email) == ("u1", "u@example.test")


@pytest.mark.parametrize(
    "overrides",
    [
        {"nonce": "other"},
        {"aud": "someone-else"},
        {"iss": "https://evil.test"},
        {"exp": int(time.time()) - 3600},
        {"sub": None},
    ],
    ids=["nonce", "audience", "issuer", "expired", "missing-sub"],
)
def test_invalid_id_tokens_rejected(
    verifier: OidcClient, signing_key: rsa.RSAPrivateKey, overrides: dict[str, Any]
) -> None:
    with pytest.raises(OidcError):
        verifier.verify_id_token(token(signing_key, **overrides), nonce="n1")


def test_token_signed_by_unknown_key_rejected(verifier: OidcClient) -> None:
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(OidcError):
        verifier.verify_id_token(token(attacker), nonce="n1")


def test_unsigned_and_hmac_tokens_rejected(verifier: OidcClient) -> None:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "u1",
        "iat": now,
        "exp": now + 60,
        "nonce": "n1",
    }
    for forged in (
        jwt.encode(claims, None, algorithm="none"),
        jwt.encode(claims, "secret-secret-secret-secret-1234", algorithm="HS256"),
    ):
        with pytest.raises(OidcError):
            verifier.verify_id_token(forged, nonce="n1")


def test_unverified_email_is_not_trusted(verifier: OidcClient, signing_key: rsa.RSAPrivateKey) -> None:
    claims = verifier.verify_id_token(token(signing_key, email_verified=False), nonce="n1")
    assert claims.email is None


def test_backchannel_rewrites_server_calls_but_keeps_public_issuer(signing_key: rsa.RSAPrivateKey) -> None:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)  # type: ignore[assignment]
    jwk.update({"kid": "k1", "alg": "RS256"})
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/a",
                    "token_endpoint": f"{ISSUER}/t",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        return httpx.Response(200, json={"keys": [jwk]})

    settings = Settings(
        oidc_issuer=ISSUER,
        oidc_client_id=CLIENT_ID,
        env="test",
        oidc_backchannel_url="http://internal-idp:8001",
    )
    client = OidcClient(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.verify_id_token(token(signing_key), nonce="n1").subject == "u1"
    assert set(hosts) == {"internal-idp"}
    assert client.authorization_url(state="s", nonce="n", code_challenge="c" * 43).startswith(f"{ISSUER}/a?")
