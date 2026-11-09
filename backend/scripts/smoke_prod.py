"""Smoke-test a deployed instance from the outside, with the standard library only.

    python backend/scripts/smoke_prod.py https://aos-web.onrender.com
    python backend/scripts/smoke_prod.py https://aos-web.onrender.com --expect-commit 1a2b3c4 --json out.json
    python backend/scripts/smoke_prod.py http://127.0.0.1:10000 --allow-http --idp-unreachable  # CI

Read-only: it never signs in and never writes data (the one POST is a cross-origin access
request, which the server must refuse before touching the database). Exit code 0 when every
check passes. Used after every deploy and in both rollback rehearsals
(docs/operations/deploy-render.md).
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.client import HTTPResponse
from typing import Any
from urllib.parse import parse_qs, urlsplit

TIMEOUT = 20


@dataclass
class Result:
    name: str
    ok: bool
    detail: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    cookies: list[str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def fetch(
    url: str, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None
) -> Reply:
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})  # noqa: S310
    try:
        response: HTTPResponse = _opener.open(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as error:  # 3xx/4xx/5xx still carry headers and a body
        response = error  # type: ignore[assignment]
    with response:
        return Reply(
            status=response.status,
            headers={k.lower(): v for k, v in response.headers.items()},
            cookies=response.headers.get_all("set-cookie") or [],
            body=response.read(),
        )


def run(
    base: str,
    *,
    allow_http: bool,
    expect_commit: str | None,
    expect_mode: str | None,
    idp_unreachable: bool = False,
) -> list[Result]:
    results: list[Result] = []

    def check(name: str, condition: bool, detail: str) -> None:
        results.append(Result(name, bool(condition), detail))

    secure = base.startswith("https://")
    check(
        "https", secure or allow_http, "public URL uses https" if secure else "http allowed by --allow-http"
    )

    health = fetch(f"{base}/healthz")
    check(
        "liveness", health.status == 200 and health.json() == {"status": "ok"}, f"/healthz -> {health.status}"
    )
    ready = fetch(f"{base}/readyz")
    check("readiness", ready.status == 200, f"/readyz -> {ready.status} {ready.body[:160]!r}")

    version = fetch(f"{base}/version")
    info = version.json() if version.status == 200 else {}
    check("version", version.status == 200 and bool(info.get("version")), f"/version -> {info}")
    if expect_commit:
        commit = str(info.get("commit") or "")
        check(
            "expected build",
            bool(commit) and (commit.startswith(expect_commit) or expect_commit.startswith(commit)),
            f"serving commit {commit or 'unknown'}, expected {expect_commit}",
        )

    for header, expected in (("x-content-type-options", "nosniff"), ("x-frame-options", "DENY")):
        check(
            f"header {header}",
            health.headers.get(header) == expected,
            f"{header}: {health.headers.get(header)}",
        )
    check("request id", bool(health.headers.get("x-request-id")), "responses carry x-request-id")

    page = fetch(f"{base}/")
    csp = page.headers.get("content-security-policy", "")
    check("app shell", page.status == 200 and b'id="root"' in page.body, f"/ -> {page.status}")
    check(
        "content security policy", "frame-ancestors 'none'" in csp and "script-src 'self'" in csp, csp[:120]
    )
    deep = fetch(f"{base}/runs/client-side-route")
    check(
        "client-side routes", deep.status == 200 and b'id="root"' in deep.body, f"deep link -> {deep.status}"
    )
    icon = fetch(f"{base}/favicon.svg")
    check("favicon", icon.status == 200 and b"<svg" in icon.body, f"/favicon.svg -> {icon.status}")

    check("no API docs in prod", fetch(f"{base}/api/openapi.json").status == 404, "/api/openapi.json hidden")
    check("metrics not public", fetch(f"{base}/metrics").status in (401, 404), "/metrics needs a token")
    me = fetch(f"{base}/api/v1/auth/me")
    envelope = me.json().get("error", {}) if me.status == 401 else {}
    check(
        "sign-in required",
        me.status == 401 and envelope.get("code") == "unauthenticated",
        f"/me -> {me.status}",
    )

    config = fetch(f"{base}/api/v1/auth/config")
    settings = config.json() if config.status == 200 else {}
    check("auth config", config.status == 200 and bool(settings.get("provider_label")), f"{settings}")
    if expect_mode:
        check("signup mode", settings.get("signup_mode") == expect_mode, f"expected {expect_mode}")

    login = fetch(f"{base}/api/v1/auth/login?next=/")
    location = login.headers.get("location", "")
    if idp_unreachable:
        check(
            "identity provider outage is handled",
            login.status == 302 and location == "/signin?error=provider_unavailable",
            f"{login.status} -> {location}",
        )
    else:
        params = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
        check(
            "login redirects to the identity provider",
            login.status == 302 and params.get("code_challenge_method") == "S256" and "state" in params,
            f"{login.status} -> {urlsplit(location).netloc or location[:80]}",
        )
        check(
            "redirect URI",
            params.get("redirect_uri") == f"{base}/api/v1/auth/callback",
            f"redirect_uri={params.get('redirect_uri')}",
        )
        cookie = next((c for c in login.cookies if c.startswith("aos_login=")), "").lower()
        flags_ok = (
            "httponly" in cookie and "samesite=lax" in cookie and "path=/api/v1/auth/callback" in cookie
        )
        check(
            "login cookie",
            bool(cookie) and flags_ok and (not secure or "secure" in cookie),
            cookie[:20] + "...",
        )

    denied = fetch(f"{base}/api/v1/auth/callback?error=access_denied")
    check(
        "callback errors return to sign-in",
        denied.status == 302 and denied.headers.get("location") == "/signin?error=provider_denied",
        f"{denied.status} -> {denied.headers.get('location')}",
    )
    cross = fetch(
        f"{base}/api/v1/access-requests",
        method="POST",
        headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
        data=b'{"email": "smoke@example.invalid", "name": "Smoke"}',
    )
    # 403 since the access model (ADR 0021). Builds that predate the endpoint have no public
    # write to refuse: they answer 404, or 405 when the SPA's GET-only fallback matches the path.
    check(
        "cross-origin writes refused",
        cross.status in (403, 404, 405),
        f"cross-origin access request -> {cross.status}",
    )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("url", help="public base URL, e.g. https://aos-web.onrender.com")
    parser.add_argument("--allow-http", action="store_true", help="permit http (local or CI containers)")
    parser.add_argument("--expect-commit", help="fail unless /version reports this commit (prefix)")
    parser.add_argument("--expect-signup-mode", choices=["invite", "request", "open"])
    parser.add_argument(
        "--idp-unreachable",
        action="store_true",
        help="the identity provider is deliberately unreachable (CI): expect the friendly outage redirect",
    )
    parser.add_argument("--json", dest="json_path", help="also write the results to this file")
    args = parser.parse_args(argv)
    base = args.url.rstrip("/")

    started = datetime.now(UTC)
    try:
        results = run(
            base,
            allow_http=args.allow_http,
            expect_commit=args.expect_commit,
            expect_mode=args.expect_signup_mode,
            idp_unreachable=args.idp_unreachable,
        )
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        results = [Result("reachable", False, f"{type(exc).__name__}: {exc}")]
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"{'PASS' if r.ok else 'FAIL'}  {r.name.ljust(width)}  {r.detail}")
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed against {base}")
    if args.json_path:
        record = {
            "url": base,
            "started_at": started.isoformat(),
            "passed": not failed,
            "results": [asdict(r) for r in results],
        }
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
