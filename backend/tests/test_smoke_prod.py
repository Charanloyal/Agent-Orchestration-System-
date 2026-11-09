"""scripts/smoke_prod.py, run against the real app (through the test client) and the real dev
identity provider, so the deploy checks cannot drift from what the app actually does."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, create_app
from tests.conftest import BACKEND_DIR

# Checks that only hold with production settings (the test app runs with env=test).
PROD_ONLY = {"no API docs in prod", "metrics not public"}


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_prod", BACKEND_DIR / "scripts" / "smoke_prod.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db: object) -> ModuleType:
    (tmp_path / "index.html").write_text('<!doctype html><div id="root"></div>', encoding="utf-8")
    (tmp_path / "favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    spa = create_app(Settings(env="test", static_dir=tmp_path))
    spa.dependency_overrides = app.dependency_overrides  # share overrides such as oidc_against
    client = TestClient(spa)
    module = load_script()

    def fetch(
        url: str, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None
    ) -> Any:
        response = client.request(
            method,
            url.removeprefix("http://testserver"),
            headers=headers or {},
            content=data,
            follow_redirects=False,
        )
        return module.Reply(
            status=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            cookies=response.headers.get_list("set-cookie"),
            body=response.content,
        )

    monkeypatch.setattr(module, "fetch", fetch)
    return module


def test_smoke_checks_pass_against_the_app(smoke: ModuleType, oidc_against: Any) -> None:
    results = smoke.run("http://testserver", allow_http=True, expect_commit=None, expect_mode="open")
    failed = {r.name for r in results if not r.ok}
    assert failed == PROD_ONLY, [(r.name, r.detail) for r in results if not r.ok]
    names = {r.name for r in results}
    assert {"login redirects to the identity provider", "redirect URI", "login cookie"} <= names
    cross = next(r for r in results if r.name == "cross-origin writes refused")
    assert cross.detail.endswith("-> 403"), "this build has the endpoint, so its origin check must refuse"


def test_smoke_checks_report_a_wrong_build_and_an_identity_provider_outage(smoke: ModuleType) -> None:
    results = smoke.run(
        "http://testserver", allow_http=True, expect_commit="deadbeef", expect_mode=None, idp_unreachable=True
    )
    by_name = {r.name: r for r in results}
    assert not by_name["expected build"].ok, "an unknown commit never matches"
    assert by_name["identity provider outage is handled"].ok


def test_unreachable_url_fails_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    assert load_script().main(["http://127.0.0.1:9", "--allow-http"]) == 1
    assert "FAIL  reachable" in capsys.readouterr().out
