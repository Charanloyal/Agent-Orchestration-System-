"""Evaluation cases, their offline corpus folders, and machine-readable fixtures.

Layout (eval/corpus/v1/<case_id>/):
    docs/*.json     corpus documents for CorpusSearch (one folder per case, no cross-talk)
    fixture.json    optional: {"search_faults": {"status", "times"},
                               "model_fault": {"kind"},
                               "uploads": [{"filename", "text"}]}
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.contracts.evaluation import EvalCase

REPO_ROOT = Path(__file__).resolve().parents[2]
BRIEFS_DIR = REPO_ROOT / "eval" / "briefs"
CORPUS_DIR = REPO_ROOT / "eval" / "corpus" / "v1"

Split = Literal["dev", "heldout"]


@dataclass(frozen=True)
class SearchFault:
    status: int
    times: int


@dataclass(frozen=True)
class Upload:
    filename: str
    text: str


@dataclass(frozen=True)
class CaseFixture:
    case: EvalCase
    docs_dir: Path
    search_fault: SearchFault | None = None
    model_fault: str | None = None
    uploads: tuple[Upload, ...] = field(default_factory=tuple)

    @property
    def case_id(self) -> str:
        return self.case.case_id


def load_cases(split: Split, case_ids: list[str] | None = None) -> list[CaseFixture]:
    paths = sorted((BRIEFS_DIR / split).glob(f"{split}-*.json"))
    fixtures = [load_fixture(EvalCase.model_validate_json(p.read_text(encoding="utf-8"))) for p in paths]
    if case_ids:
        wanted = set(case_ids)
        if unknown := wanted - {f.case_id for f in fixtures}:
            raise ValueError(f"unknown case ids for split {split}: {sorted(unknown)}")
        fixtures = [f for f in fixtures if f.case_id in wanted]
    return fixtures


def load_fixture(case: EvalCase) -> CaseFixture:
    case_dir = CORPUS_DIR / case.case_id
    raw: dict[str, Any] = {}
    if (case_dir / "fixture.json").exists():
        raw = json.loads((case_dir / "fixture.json").read_text(encoding="utf-8"))
    search = raw.get("search_faults")
    model = raw.get("model_fault")
    return CaseFixture(
        case=case,
        docs_dir=case_dir / "docs",
        search_fault=SearchFault(int(search["status"]), int(search["times"])) if search else None,
        model_fault=str(model["kind"]) if model else None,
        uploads=tuple(Upload(str(u["filename"]), str(u["text"])) for u in raw.get("uploads") or []),
    )


def corpus_digest() -> str:
    """SHA-256 of the corpus manifest, recorded with every result set."""
    manifest = CORPUS_DIR / "MANIFEST.json"
    return hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else "missing"
