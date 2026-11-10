"""End-to-end OIDC sign-in against the real dev issuer over HTTP, plus ID-token verification
edge cases using locally signed tokens."""

import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from app.api.auth import safe_next_path
from app.auth.oidc import OidcClient, OidcError, verified_email
from app.config import Settings


def sign_in_via_dev_issuer(client: TestClient, subject: str, next_path: str = "/runs") -> httpx.Response:
    authorize_url = start_sign_in(client, next_path)
    return client.get(consent(authorize_url, subject), follow_redirects=False)


def start_sign_in(client: TestClient, next_path: str = "/runs") -> str:
    start = client.get("/api/v1/auth/login", params={"next": next_path}, follow_redirects=False)
    assert start.status_code == 302, start.headers.get("location")
    return start.headers["location"]


def consent(authorize_url: str, subject: str) -> str:
    """Pick `subject` on the dev issuer's page; returns the app callback path and query."""
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
        answer = browser.post(authorize_url.split("?")[0], data={**form, "subject": subject})
    assert answer.status_code == 302
    callback = urlparse(answer.headers["location"])
    return f"{callback.path}?{callback.query}"


def test_full_sign_in_flow_creates_session(client: TestClient, db: object, oidc_against: Any) -> None:
    response = sign_in_via_dev_issuer(client, "dev-alice")
    assert response.status_code == 302
    assert response.headers["location"] == "/runs"
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("aos_session=")).lower()
    assert "httponly" in session_cookie
    assert "samesite=lax" in session_cookie
    assert any(c.startswith("aos_login=") and "max-age=0" in c.lower() for c in cookies), (
        "the one-time login cookie is cleared"
    )

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "alice@example.test"
    assert body["display_name"] == "Alice Analyst"
    assert len(body["csrf_token"]) >= 32
    assert body["deployment"] == {"environment": "test", "agent_mode": "fake"}, "UI can label demo agents"
    assert body["is_platform_admin"] is False and body["can_create_workspace"] is True


def test_login_binds_the_attempt_to_this_browser(client: TestClient, db: object, oidc_against: Any) -> None:
    start = client.get("/api/v1/auth/login", follow_redirects=False)
    cookie = start.headers["set-cookie"]
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    assert cookie.startswith(f"aos_login={state};")
    lowered = cookie.lower()
    assert "httponly" in lowered and "samesite=lax" in lowered
    assert "path=/api/v1/auth/callback" in lowered and "max-age=600" in lowered


def test_secure_cookies_carry_browser_enforced_prefixes() -> None:
    """With Secure cookies (required in prod) the session cookie is `__Host-` (Secure, Path=/,
    no Domain: no subdomain can set or shadow it) and the login cookie, which is scoped to the
    callback path, is `__Secure-`. Existing sessions simply sign in again."""
    from starlette.responses import Response

    from app.auth.sessions import set_login_cookie, set_session_cookie

    secure = Settings(cookie_secure=True)
    assert (secure.session_cookie, secure.login_cookie) == ("__Host-aos_session", "__Secure-aos_login")
    response = Response()
    set_session_cookie(response, "token", secure)
    set_login_cookie(response, "state", secure)
    session, login = response.headers.getlist("set-cookie")
    assert session.startswith("__Host-aos_session=token;") and "Path=/;" in session
    assert "Domain" not in session and "Secure" in session
    assert login.startswith("__Secure-aos_login=state;") and "Secure" in login
    plain = Settings(cookie_secure=False)
    assert (plain.session_cookie, plain.login_cookie) == ("aos_session", "aos_login"), (
        "browsers reject prefixed cookies without Secure, so local http keeps plain names"
    )


def test_callback_from_another_browser_is_refused(client: TestClient, db: object, oidc_against: Any) -> None:
    """Login CSRF: an attacker's valid code and state, replayed in a victim's browser, must
    not sign the victim into the attacker's account."""
    callback = consent(start_sign_in(client), "dev-mallory")
    client.cookies.clear()
    response = client.get(callback, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/signin?error=login_expired"
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    ("query", "error"),
    [
        ({"error": "access_denied"}, "provider_denied"),
        ({"error": "server_error"}, "provider_error"),
        ({"state": "s"}, "login_failed"),
        ({"code": "c", "state": "forged"}, "login_expired"),
    ],
)
def test_callback_failures_return_to_the_sign_in_page(
    client: TestClient, db: object, query: dict[str, str], error: str
) -> None:
    response = client.get("/api/v1/auth/callback", params=query, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == f"/signin?error={error}"


def test_auth_config_is_public_and_reveals_no_accounts(client: TestClient) -> None:
    response = client.get("/api/v1/auth/config")
    assert response.status_code == 200
    assert response.json() == {"provider_label": "dev sign-in", "signup_mode": "open"}


@pytest.mark.parametrize(
    ("issuer", "label"),
    [
        ("https://accounts.google.com", "Google"),
        ("https://login.microsoftonline.com/tenant/v2.0", "Microsoft"),
        ("https://sso.example.org", "your organization"),
        ("http://127.0.0.1:8001", "dev sign-in"),
    ],
)
def test_provider_label_is_derived_from_the_issuer(issuer: str, label: str) -> None:
    assert Settings(env="test", oidc_issuer=issuer).provider_label == label
    assert (
        Settings(env="test", oidc_issuer=issuer, oidc_provider_label="Acme SSO").provider_label == "Acme SSO"
    )


def test_callback_state_is_single_use(client: TestClient, db: object, oidc_against: Any) -> None:
    callback = consent(start_sign_in(client), "dev-bob")
    first = client.get(callback, follow_redirects=False)
    assert first.status_code == 302 and first.headers["location"] == "/runs"
    replay = client.get(callback, follow_redirects=False)
    assert replay.status_code == 302
    assert replay.headers["location"] == "/signin?error=login_expired"


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


@pytest.mark.parametrize(
    ("email_verified", "trusted"),
    [(True, True), (False, False), (None, False), ("true", False), (1, False)],
    ids=["true", "false", "missing", "string", "number"],
)
def test_only_an_explicitly_verified_email_is_trusted(
    verifier: OidcClient, signing_key: rsa.RSAPrivateKey, email_verified: object, trusted: bool
) -> None:
    claims = verifier.verify_id_token(token(signing_key, email_verified=email_verified), nonce="n1")
    assert claims.email == ("u@example.test" if trusted else None)
    assert claims.name == "U", "the display name never falls back to an unverified email"


ENTRA = "https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0"


@pytest.mark.parametrize(
    ("issuer", "claims", "trusted"),
    [
        (ENTRA, {"email": "a@contoso.example", "xms_edov": True}, True),
        (ENTRA, {"email": "a@contoso.example", "xms_edov": False}, False),
        (ENTRA, {"email": "a@contoso.example"}, False),
        (ISSUER, {"email": "a@contoso.example", "xms_edov": True}, False),
        ("https://accounts.google.com", {"email": "a@gmail.example"}, False),
        (ENTRA, {"email": "not-an-address", "email_verified": True}, False),
    ],
    ids=[
        "entra-domain-verified",
        "entra-edov-false",
        "entra-missing",
        "xms-edov-elsewhere",
        "google-missing",
        "no-at",
    ],
)
def test_microsoft_entra_vouches_with_xms_edov_only(
    issuer: str, claims: dict[str, object], trusted: bool
) -> None:
    assert verified_email(claims, issuer) == (claims["email"] if trusted else None)


GOOGLE = "https://accounts.google.com"


@pytest.mark.parametrize(
    ("iss", "accepted"),
    [(GOOGLE, True), ("accounts.google.com", True), ("https://accounts.google.com.evil.test", False)],
)
def test_google_issuer_is_accepted_in_both_documented_forms(
    signing_key: rsa.RSAPrivateKey, iss: str, accepted: bool
) -> None:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)  # type: ignore[assignment]
    jwk.update({"kid": "k1", "alg": "RS256"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": GOOGLE,
                    "authorization_endpoint": f"{GOOGLE}/o/oauth2/v2/auth",
                    "token_endpoint": "https://oauth2.googleapis.com/token",
                    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
                },
            )
        return httpx.Response(200, json={"keys": [jwk]})

    settings = Settings(oidc_issuer=GOOGLE, oidc_client_id=CLIENT_ID, env="test")
    google = OidcClient(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    if accepted:
        claims = google.verify_id_token(token(signing_key, iss=iss), nonce="n1")
        assert claims.issuer == GOOGLE, "users are keyed by the configured issuer, whatever the form"
    else:
        with pytest.raises(OidcError):
            google.verify_id_token(token(signing_key, iss=iss), nonce="n1")


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
