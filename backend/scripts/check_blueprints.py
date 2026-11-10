"""Checks the Render blueprints (render*.yaml at the repository root) before a deploy (ADR 0023).

    python backend/scripts/check_blueprints.py [--schema render.schema.json]

1. With --schema, validates every blueprint against Render's published Blueprint schema
   (https://render.com/schema/render.yaml.json; needs `pip install jsonschema pyyaml`).
2. Always checks that each blueprint starts the image the way CI's deploy-image job does, so
   a blueprint cannot drift from what CI proves:
   - web+worker: the web service uses the image's default command and migrates in its
     pre-deploy step; the worker runs `python -m app.workers.runner` and carries no web-only
     settings (sign-in, public URL, platform admins);
   - single: one web service runs `python -m app.serve --migrate --with-worker`.
   Every service and database states the same region, and the values in WEB_VALUES and
   BLUEPRINT_VALUES (trusted proxy hops, retention) are set as decided.

Prints one line per blueprint and exits 1 on any problem.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
MIGRATE = "alembic upgrade head"
WORKER = "python -m app.workers.runner"
SINGLE = "python -m app.serve --migrate --with-worker"
WEB_ONLY = (
    "AOS_PUBLIC_URL",
    "AOS_OIDC_",
    "AOS_PLATFORM_ADMIN_EMAILS",
    "AOS_COOKIE_",
    "AOS_TRUSTED_PROXY_HOPS",
)
# Values every web service must set on Render (key -> value), with the decision behind each.
WEB_VALUES = {
    "AOS_TRUSTED_PROXY_HOPS": "1",  # ADR 0025: the platform proxy appends the client address
}
# Values a blueprint must state wherever it sets them (services and groups), at least once.
BLUEPRINT_VALUES = {
    # Owner's RUN_RETENTION_DAYS=0: demo runs and uploads must survive until the viva.
    "AOS_RETENTION_RUN_DAYS": "0",
    "AOS_RETENTION_UPLOAD_DAYS": "0",
}


def env_values(service: dict[str, Any]) -> dict[str, str]:
    return {v["key"]: str(v["value"]) for v in service.get("envVars", []) if "key" in v and "value" in v}


@dataclass
class Blueprint:
    path: Path
    topology: str = "?"
    region: str = "?"
    problems: list[str] = field(default_factory=list)


def blueprint_files(root: Path = ROOT) -> list[Path]:
    return sorted(root.glob("render*.yaml"))


def check(path: Path) -> Blueprint:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    result = Blueprint(path)
    services = doc.get("services", [])
    webs = [s for s in services if s.get("type") == "web"]
    workers = [s for s in services if s.get("type") == "worker"]
    if len(webs) != 1:
        result.problems.append(f"expected exactly one web service, found {len(webs)}")
        return result
    web = webs[0]
    if web.get("healthCheckPath") != "/readyz":
        result.problems.append("the web service must use healthCheckPath /readyz")
    values = env_values(web)
    for key, expected in WEB_VALUES.items():
        if values.get(key) != expected:
            result.problems.append(f"the web service must set {key}={expected}")
    if workers:
        result.topology = "web+worker"
        if web.get("dockerCommand") is not None:
            result.problems.append("the web service must use the image's default command")
        if web.get("preDeployCommand") != MIGRATE:
            result.problems.append(f"the web service must run '{MIGRATE}' as its pre-deploy command")
        for worker in workers:
            if worker.get("dockerCommand") != WORKER:
                result.problems.append(f"worker {worker.get('name')} must run '{WORKER}'")
            keys = [v.get("key", "") for v in worker.get("envVars", []) if "key" in v]
            if leaked := [k for k in keys if k.startswith(WEB_ONLY)]:
                result.problems.append(f"the worker needs no web settings: {', '.join(leaked)}")
    else:
        result.topology = "single"
        if web.get("dockerCommand") != SINGLE:
            result.problems.append(f"the single web service must run '{SINGLE}'")
    regions = {str(item.get("region")) for item in [*services, *doc.get("databases", [])]}
    if len(regions) == 1 and "None" not in regions:
        result.region = regions.pop()
    else:
        result.problems.append(f"every service and database needs the same region, found {sorted(regions)}")
    stated = [env_values(item) for item in [*services, *doc.get("envVarGroups", [])]]
    for key, expected in BLUEPRINT_VALUES.items():
        found = {values[key] for values in stated if key in values}
        if found != {expected}:
            result.problems.append(f"the blueprint must set {key}={expected}, found {sorted(found)}")
    return result


def schema_problems(path: Path, schema: dict[str, Any]) -> list[str]:
    import jsonschema  # only with --schema; CI installs it

    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        f"schema: {'/'.join(map(str, e.path)) or '<root>'}: {e.message[:300]}"
        for e in jsonschema.Draft7Validator(schema).iter_errors(doc)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--schema", type=Path, help="Render's Blueprint JSON schema, downloaded")
    args = parser.parse_args(argv)
    schema = json.loads(args.schema.read_text(encoding="utf-8")) if args.schema else None
    files = blueprint_files()
    if not files:
        print("no render*.yaml found")
        return 1
    failed = False
    for path in files:
        result = check(path)
        if schema is not None:
            result.problems.extend(schema_problems(path, schema))
        print(f"{path.name}: {result.topology} in {result.region}" + (" (schema checked)" if schema else ""))
        for problem in result.problems:
            print(f"  FAIL {problem}")
        failed = failed or bool(result.problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
