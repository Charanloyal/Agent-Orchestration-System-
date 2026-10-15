import json
from pathlib import Path

import pytest

from app.contracts import EvalCase
from scripts.export_schemas import SCHEMA_DIR, render_schemas

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_DIR = REPO_ROOT / "eval" / "briefs" / "dev"
DEV_FILES = sorted(DEV_DIR.glob("*.json"))


@pytest.mark.parametrize("filename", sorted(render_schemas()))
def test_checked_in_schema_matches_model(filename: str) -> None:
    path = SCHEMA_DIR / filename
    assert path.exists(), f"missing {path}; run: python -m scripts.export_schemas"
    expected = render_schemas()[filename]
    assert path.read_text(encoding="utf-8") == expected, (
        f"{filename} is stale; run: python -m scripts.export_schemas"
    )


def test_twenty_dev_briefs_exist() -> None:
    assert len(DEV_FILES) == 20


@pytest.mark.parametrize("path", DEV_FILES, ids=lambda p: p.stem)
def test_dev_brief_is_valid(path: Path) -> None:
    case = EvalCase.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert case.split == "dev"
    assert case.case_id == path.stem


def test_dev_set_covers_every_category() -> None:
    categories = {json.loads(p.read_text(encoding="utf-8"))["category"] for p in DEV_FILES}
    assert categories == {
        "answerable",
        "conflicting_evidence",
        "unavailable_evidence",
        "stale_sources",
        "malicious_content",
        "provider_failure",
    }
