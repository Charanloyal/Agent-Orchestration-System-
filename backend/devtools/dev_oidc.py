"""Local development OpenID Connect issuer. NOT FOR PRODUCTION.

A tiny, standards-shaped issuer so the real OIDC client code path (authorization code +
PKCE S256, RS256 ID tokens, JWKS) can be exercised locally and in tests without an external
identity provider. It refuses to start when AOS_ENV=prod and binds to 127.0.0.1 only.

Run:  python -m devtools.dev_oidc            (from backend/, listens on 127.0.0.1:8001)
"""

import base64
import hashlib
import html
import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jwt.algorithms import RSAAlgorithm


@dataclass(frozen=True)
class DevUser:
    subject: str
    email: str
    name: str
    hint: str


DEFAULT_USERS = (
    DevUser(
        "dev-alice",
        "alice@example.test",
        "Alice Analyst",
        "analyst in the demo workspace",
    ),
    DevUser("dev-bob", "bob@example.test", "Bob Reviewer", "reviewer in the demo workspace"),
    DevUser("dev-carol", "carol@example.test", "Carol Admin", "admin in the demo workspace"),
    DevUser(
        "dev-mallory",
        "mallory@example.test",
        "Mallory Outsider",
        "member of another workspace",
    ),
)

_CODE_TTL_SECONDS = 60
_TOKEN_TTL_SECONDS = 300


@dataclass
class _PendingCode:
    client_id: str
    redirect_uri: str
    code_challenge: str
    nonce: str
    user: DevUser
    expires_at: float


def create_dev_issuer(
    issuer: str,
    *,
    client_id: str,
    redirect_uris: list[str],
    users: tuple[DevUser, ...] = DEFAULT_USERS,
) -> FastAPI:
    if os.environ.get("AOS_ENV", "dev") == "prod":
        raise RuntimeError("The dev OIDC issuer must never run with AOS_ENV=prod")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = secrets.token_hex(8)
    public_jwk: dict[str, Any] = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)  # type: ignore[assignment]
    public_jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    users_by_subject = {u.subject: u for u in users}
    codes: dict[str, _PendingCode] = {}
    lock = threading.Lock()

    app = FastAPI(title="Dev OIDC issuer (local only)", docs_url=None, redoc_url=None)

    @app.get("/.well-known/openid-configuration")
    def discovery() -> dict[str, Any]:
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "jwks_uri": f"{issuer}/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["openid", "email", "profile"],
            "token_endpoint_auth_methods_supported": ["none"],
        }

    @app.get("/jwks")
    def jwks() -> dict[str, Any]:
        return {"keys": [public_jwk]}

    def _check_request(cid: str, redirect_uri: str, method: str, challenge: str, scope: str) -> None:
        if cid != client_id or redirect_uri not in redirect_uris:
            raise HTTPException(400, "unknown client or redirect_uri")
        if method != "S256" or len(challenge) < 43:
            raise HTTPException(400, "PKCE S256 required")
        if "openid" not in scope.split():
            raise HTTPException(400, "openid scope required")

    @app.get("/authorize", response_class=HTMLResponse)
    def authorize_page(
        client_id_: Annotated[str, Query(alias="client_id")],
        redirect_uri: str,
        state: str,
        nonce: str,
        code_challenge: str,
        code_challenge_method: str,
        response_type: str = "code",
        scope: str = "openid",
    ) -> str:
        if response_type != "code":
            raise HTTPException(400, "response_type must be code")
        _check_request(client_id_, redirect_uri, code_challenge_method, code_challenge, scope)
        hidden = {
            "client_id": client_id_,
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "scope": scope,
        }
        fields = "".join(
            f'<input type="hidden" name="{k}" value="{html.escape(v, quote=True)}">'
            for k, v in hidden.items()
        )
        buttons = "".join(
            f'<button name="subject" value="{html.escape(u.subject)}">'
            f"<strong>{html.escape(u.name)}</strong><span>{html.escape(u.email)} · {html.escape(u.hint)}</span>"
            "</button>"
            for u in users
        )
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Dev sign-in</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font-family:system-ui,sans-serif;background:#f6f8fa;margin:0}}
main{{max-width:28rem;margin:4rem auto;background:#fff;border:1px solid #d1d9e0;border-radius:12px;padding:2rem}}
p.warn{{background:#fff8c5;padding:.5rem .75rem;border-radius:6px}}
button{{display:flex;flex-direction:column;align-items:flex-start;width:100%;text-align:left;
margin:.5rem 0;padding:.75rem 1rem;border:1px solid #d1d9e0;border-radius:8px;background:#fff;cursor:pointer;font:inherit}}
button:hover,button:focus{{border-color:#0969da;outline:2px solid #0969da33}}
span{{color:#59636e;font-size:.875rem}}</style></head><body><main>
<h1>Local development sign-in</h1>
<p class="warn">This is a test identity provider for local demos only.</p>
<form method="post" action="{issuer}/authorize">{fields}{buttons}</form></main></body></html>"""

    @app.post("/authorize")
    def authorize_submit(
        client_id_: Annotated[str, Form(alias="client_id")],
        redirect_uri: Annotated[str, Form()],
        state: Annotated[str, Form()],
        nonce: Annotated[str, Form()],
        code_challenge: Annotated[str, Form()],
        subject: Annotated[str, Form()],
        scope: Annotated[str, Form()] = "openid",
    ) -> RedirectResponse:
        _check_request(client_id_, redirect_uri, "S256", code_challenge, scope)
        user = users_by_subject.get(subject)
        if user is None:
            raise HTTPException(400, "unknown user")
        code = secrets.token_urlsafe(32)
        with lock:
            codes[code] = _PendingCode(
                client_id_,
                redirect_uri,
                code_challenge,
                nonce,
                user,
                time.time() + _CODE_TTL_SECONDS,
            )
        return RedirectResponse(f"{redirect_uri}?{urlencode({'code': code, 'state': state})}", 302)

    @app.post("/token")
    def token(
        grant_type: Annotated[str, Form()],
        code: Annotated[str, Form()],
        redirect_uri: Annotated[str, Form()],
        client_id_: Annotated[str, Form(alias="client_id")],
        code_verifier: Annotated[str, Form()],
    ) -> JSONResponse:
        with lock:
            pending = codes.pop(code, None)  # single use
        if grant_type != "authorization_code" or pending is None or pending.expires_at < time.time():
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        if pending.client_id != client_id_ or pending.redirect_uri != redirect_uri:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        expected = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=")
        if not secrets.compare_digest(expected.decode(), pending.code_challenge):
            return JSONResponse({"error": "invalid_grant", "error_description": "PKCE"}, status_code=400)
        now = int(time.time())
        claims = {
            "iss": issuer,
            "sub": pending.user.subject,
            "aud": client_id_,
            "iat": now,
            "exp": now + _TOKEN_TTL_SECONDS,
            "nonce": pending.nonce,
            "email": pending.user.email,
            "email_verified": True,
            "name": pending.user.name,
        }
        id_token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})
        return JSONResponse(
            {
                "access_token": secrets.token_urlsafe(32),
                "token_type": "Bearer",
                "expires_in": _TOKEN_TTL_SECONDS,
                "id_token": id_token,
            },
            headers={"Cache-Control": "no-store"},
        )

    return app


def main() -> None:
    import uvicorn

    host = os.environ.get("AOS_DEV_OIDC_HOST", "127.0.0.1")
    port = int(os.environ.get("AOS_DEV_OIDC_PORT", "8001"))
    issuer = os.environ.get("AOS_DEV_OIDC_ISSUER", f"http://127.0.0.1:{port}").rstrip("/")
    public_url = os.environ.get("AOS_PUBLIC_URL", "http://127.0.0.1:5173").rstrip("/")
    app = create_dev_issuer(
        issuer,
        client_id=os.environ.get("AOS_OIDC_CLIENT_ID", "aos-local"),
        redirect_uris=[f"{public_url}/api/v1/auth/callback"],
    )
    # Inside a container the host must be 0.0.0.0 for port publishing; the container
    # network itself is still private to the Compose project.
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
