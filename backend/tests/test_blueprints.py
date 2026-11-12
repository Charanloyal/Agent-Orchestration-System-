"""scripts/check_blueprints.py: every Render blueprint starts the image the way CI proves it
(ADR 0023). The schema half needs network access and runs in CI's deploy-image job."""

import importlib.util
from pathlib import Path
from types import ModuleType

from tests.conftest import BACKEND_DIR


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_blueprints", BACKEND_DIR / "scripts" / "check_blueprints.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_blueprint_matches_a_topology_ci_starts() -> None:
    script = load_script()
    results = {path.name: script.check(path) for path in script.blueprint_files()}
    assert {name: r.problems for name, r in results.items() if r.problems} == {}
    assert {name: r.topology for name, r in results.items()} == {
        "render.yaml": "web+worker",
        "render.hybrid.yaml": "single",
        "render.free.yaml": "single",
    }
    assert {r.region for r in results.values()} == {"singapore"}, "owner's decision; fixed at creation"
    # Worst case during a deploy (old and new instances overlap), against Render's 100 (G6).
    assert {name: r.connections for name, r in results.items()} == {
        "render.yaml": 83,
        "render.hybrid.yaml": 43,
        "render.free.yaml": 43,
    }


def test_a_blueprint_that_could_exhaust_the_database_is_reported(tmp_path: Path) -> None:
    script = load_script()
    greedy = tmp_path / "render.yaml"
    greedy.write_text(
        (script.ROOT / "render.hybrid.yaml")
        .read_text(encoding="utf-8")
        .replace('key: AOS_DB_POOL_SIZE\n        value: "5"', 'key: AOS_DB_POOL_SIZE\n        value: "30"'),
        encoding="utf-8",
    )
    result = script.check(greedy)
    assert result.connections == 2 * ((30 + 5) + (30 + 5 + 1)) + 1, "web + worker child, twice, + migration"
    assert any("connections" in p for p in result.problems)


def test_drift_from_what_ci_runs_is_reported(tmp_path: Path) -> None:
    script = load_script()
    drifted = tmp_path / "render.yaml"
    drifted.write_text(
        """
services:
  - {type: web, name: web, region: oregon, healthCheckPath: /healthz, dockerCommand: uvicorn app.main:app}
  - type: worker
    name: worker
    region: frankfurt
    dockerCommand: python -m app.workers.runner --once
    envVars:
      - {key: AOS_OIDC_ISSUER, sync: false}
""",
        encoding="utf-8",
    )
    problems = " | ".join(script.check(drifted).problems)
    for expected in (
        "healthCheckPath",
        "default command",
        "pre-deploy",
        "must run",
        "AOS_OIDC_ISSUER",
        "region",
        "AOS_TRUSTED_PROXY_HOPS=2",
        "AOS_RETENTION_RUN_DAYS=0",
        "AOS_STORE_FILES=false",
    ):
        assert expected in problems
    assert script.main([]) == 0, "the repository's own blueprints pass"
