"""Command line: python -m evaluation.run [options]  (run from backend/).

Safe defaults: development split, fake agents, isolated database. Held-out cases and live
providers each need an explicit flag (leakage rules and ADR 0005 spending ceiling).
"""

import argparse
import os
import sys
from pathlib import Path

LIVE_CEILING_USD = 10.0


def _eval_database_url() -> str | None:
    url = os.environ.get("AOS_EVAL_DATABASE_URL")
    if url:
        return url
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("AOS_EVAL_DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return None


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m evaluation.run", description=__doc__)
    parser.add_argument("--split", choices=["dev", "heldout"], default="dev")
    parser.add_argument("--systems", default="A,B,C", help="comma-separated subset of A,B,C")
    parser.add_argument("--cases", default="", help="comma-separated case ids (default: whole split)")
    parser.add_argument("--repeats", type=int, default=3, help="repeats for the repeat subset")
    parser.add_argument("--repeat-cases", default="", help="case ids to repeat (default: first 5 answerable)")
    parser.add_argument("--live", action="store_true", help="use the configured LLM provider (costs money)")
    parser.add_argument(
        "--budget", type=float, help="maximum estimated USD for a live run (required with --live)"
    )
    parser.add_argument(
        "--confirm-heldout", action="store_true", help="acknowledge the held-out leakage rules"
    )
    parser.add_argument("--results", default=None, help="results root (default: eval/results)")
    parser.add_argument("--label", default=None, help="short label for the results folder")
    args = parser.parse_args(argv)
    if args.split == "heldout" and not args.confirm_heldout:
        parser.error(
            "held-out runs are reserved (docs/evaluation/evaluation-plan.md); pass --confirm-heldout"
        )
    if args.live:
        if args.budget is None:
            parser.error("--live requires --budget <USD>, approved under ADR 0005")
        if not 0 < args.budget <= LIVE_CEILING_USD:
            parser.error(f"--budget must be within the project ceiling of ${LIVE_CEILING_USD:.0f}")
    systems = [s.strip().upper() for s in args.systems.split(",") if s.strip()]
    if not systems or set(systems) - {"A", "B", "C"}:
        parser.error("--systems must be a subset of A,B,C")
    args.system_list = systems
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    url = _eval_database_url()
    if not url:
        print("Set AOS_EVAL_DATABASE_URL (backend/.env) to an empty, dedicated database.", file=sys.stderr)
        return 2
    # Must happen before anything reads settings or creates the engine.
    os.environ["AOS_DATABASE_URL"] = url
    os.environ.setdefault("AOS_LOG_LEVEL", "WARNING")
    os.environ.setdefault(
        "AOS_OBJECT_STORE_DIR", str(Path(__file__).resolve().parents[1] / ".data" / "eval-objects")
    )
    os.environ["AOS_AGENT_MODE"] = "llm" if args.live else "fake"

    from alembic import command
    from alembic.config import Config

    from app.config import get_settings
    from app.observability.logging import configure_logging
    from app.providers.llm import OpenAICompatibleLlm
    from app.workers.checkpointer import setup_checkpointer
    from evaluation.cases import REPO_ROOT, load_cases
    from evaluation.harness import EvaluationConfig, run_evaluation

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    setup_checkpointer(settings)

    case_ids = [c.strip() for c in args.cases.split(",") if c.strip()]
    fixtures = load_cases(args.split, case_ids or None)
    repeat_ids = [c.strip() for c in args.repeat_cases.split(",") if c.strip()] or [
        f.case_id for f in fixtures if f.case.category == "answerable"
    ][:5]
    live_llm = None
    if args.live:
        if settings.llm_api_key is None and not settings.llm_base_url:
            print("--live needs AOS_LLM_API_KEY (or a local AOS_LLM_BASE_URL).", file=sys.stderr)
            return 2
        live_llm = OpenAICompatibleLlm(settings)
    config = EvaluationConfig(
        split=args.split,
        systems=args.system_list,
        case_ids=[f.case_id for f in fixtures],
        repeats=max(1, args.repeats),
        repeat_case_ids=repeat_ids,
        mode="llm" if args.live else "fake",
        live_budget_usd=args.budget if args.live else None,
    )
    results_root = Path(args.results) if args.results else REPO_ROOT / "eval" / "results"
    out = run_evaluation(
        settings, fixtures, config, results_root, live_llm=live_llm, label=args.label or args.split
    )
    print(f"Results written to {out}")
    print((out / "summary.md").read_text(encoding="utf-8").split("## Per-run outcomes")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
