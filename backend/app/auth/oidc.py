"""Provider-agnostic OpenID Connect client: authorization code flow with PKCE (S256).

Works with any compliant issuer (Google, Microsoft Entra ID, Auth0, Keycloak) and with the
local dev issuer in devtools/dev_oidc.py. ID tokens are verified against the issuer's JWKS:
signature, issuer, audience, expiry, and nonce.
"""

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from app.config import Settings
from app.errors import AppError

ALLOWED_ID_TOKEN_ALGS = ["RS256", "PS256", "ES256"]
_METADATA_TTL_SECONDS = 3600


class OidcError(AppError):
    status_code = 400
    code = "oidc_error"


@dataclass(frozen=True)
class IdentityClaims:
    issuer: str
    subject: str
    email: str | None
    name: str


def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return verifier, challenge.decode()


class OidcClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None) -> None:
        self.settings = settings
        self.http = http or httpx.Client(timeout=settings.oidc_http_timeout_seconds)
        self._lock = threading.Lock()
        self._metadata: dict[str, Any] | None = None
        self._metadata_at = 0.0
        self._jwks: jwt.PyJWKSet | None = None

    def metadata(self) -> dict[str, Any]:
        with self._lock:
            if self._metadata and time.monotonic() - self._metadata_at < _METADATA_TTL_SECONDS:
                return self._metadata
            url = self._backchannel(f"{self.settings.oidc_issuer}/.well-known/openid-configuration")
            data = self._get_json(url)
            if data.get("issuer", "").rstrip("/") != self.settings.oidc_issuer:
                raise OidcError("Issuer metadata does not match the configured issuer")
            for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                if not isinstance(data.get(key), str):
                    raise OidcError(f"Issuer metadata missing {key}")
            self._metadata, self._metadata_at, self._jwks = data, time.monotonic(), None
            return data

    def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.settings.oidc_client_id,
            "redirect_uri": self.settings.oidc_redirect_uri,
            "scope": self.settings.oidc_scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.metadata()['authorization_endpoint']}?{urlencode(params)}"

    def exchange_code(self, *, code: str, code_verifier: str) -> dict[str, Any]:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.oidc_redirect_uri,
            "client_id": self.settings.oidc_client_id,
            "code_verifier": code_verifier,
        }
        if self.settings.oidc_client_secret is not None:
            form["client_secret"] = self.settings.oidc_client_secret.get_secret_value()
        try:
            response = self.http.post(self._backchannel(self.metadata()["token_endpoint"]), data=form)
        except httpx.HTTPError as exc:
            raise OidcError("Token endpoint unreachable") from exc
        if response.status_code != 200:
            # Do not echo the provider response; it may contain diagnostic secrets.
            raise OidcError(f"Token exchange failed (HTTP {response.status_code})")
        tokens: dict[str, Any] = response.json()
        if not isinstance(tokens.get("id_token"), str):
            raise OidcError("Token response has no id_token")
        return tokens

    def verify_id_token(self, id_token: str, *, nonce: str) -> IdentityClaims:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise OidcError("Malformed id_token") from exc
        alg = header.get("alg")
        if alg not in ALLOWED_ID_TOKEN_ALGS:
            raise OidcError("id_token uses a disallowed algorithm")
        key = self._signing_key(header.get("kid"))
        try:
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key=key,
                algorithms=[alg],
                audience=self.settings.oidc_client_id,
                issuer=self.settings.oidc_issuer,
                leeway=60,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise OidcError("id_token verification failed") from exc
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OidcError("id_token nonce mismatch")
        email = claims.get("email") if claims.get("email_verified", True) else None
        name = str(claims.get("name") or email or claims["sub"])[:200]
        return IdentityClaims(self.settings.oidc_issuer, str(claims["sub"]), email, name)

    def _signing_key(self, kid: str | None) -> Any:
        for refresh in (False, True):
            jwks = self._load_jwks(refresh)
            for jwk in jwks.keys:
                if kid is None or jwk.key_id == kid:
                    return jwk.key
        raise OidcError("No matching signing key")

    def _load_jwks(self, refresh: bool) -> jwt.PyJWKSet:
        jwks_uri = self._backchannel(self.metadata()["jwks_uri"])  # outside the lock (not re-entrant)
        with self._lock:
            if self._jwks is None or refresh:
                self._jwks = jwt.PyJWKSet.from_dict(self._get_json(jwks_uri))
            return self._jwks

    def _backchannel(self, url: str) -> str:
        """Rewrite issuer-prefixed endpoint URLs for server-to-server calls, if configured."""
        backchannel = self.settings.oidc_backchannel_url
        issuer = self.settings.oidc_issuer
        if backchannel and url.startswith(issuer):
            return backchannel.rstrip("/") + url[len(issuer) :]
        return url

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            response = self.http.get(url)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError("Identity provider unavailable") from exc
        if not isinstance(data, dict):
            raise OidcError("Unexpected identity provider response")
        return data
