"""Merge two scorers' sheets: python -m evaluation.score <scoring-dir> <scorer-a-dir> <scorer-b-dir>.

Each scorer directory holds that scorer's filled claims.csv, coverage.csv and must_not.csv.
Agreement (raw and Cohen's κ) is computed on items both scored. Final values use scorer A's
labels where the two agree and are listed for adjudication where they disagree; nothing is
silently averaged.
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluation.metrics import cohen_kappa, proportion


def read(path: Path) -> list[dict[str, str]]:
    if not path.exists() or not path.read_text("utf-8").strip():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _pairs(
    a: list[dict[str, str]], b: list[dict[str, str]], key: tuple[str, ...], field: str
) -> list[tuple[Any, str, str]]:
    index = {tuple(r[k] for k in key): r[field].strip().lower() for r in b if r.get(field, "").strip()}
    return [
        (tuple(r[k] for k in key), r[field].strip().lower(), index[tuple(r[k] for k in key)])
        for r in a
        if r.get(field, "").strip() and tuple(r[k] for k in key) in index
    ]


def merge(scoring_dir: Path, scorer_a: Path, scorer_b: Path) -> dict[str, Any]:
    key_map = json.loads((scoring_dir / "KEY.json").read_text("utf-8"))
    result: dict[str, Any] = {"agreement": {}, "disagreements": [], "by_system": defaultdict(dict)}
    specs = {
        "claims.csv": (("blind_id", "claim_id"), "support"),
        "coverage.csv": (("blind_id", "point"), "covered"),
        "must_not.csv": (("blind_id", "condition"), "violated"),
    }
    agreed: dict[str, list[tuple[Any, str]]] = {}
    for name, (key, field) in specs.items():
        pairs = _pairs(read(scorer_a / name), read(scorer_b / name), key, field)
        a_labels = [p[1] for p in pairs]
        b_labels = [p[2] for p in pairs]
        kappa = cohen_kappa(a_labels, b_labels)
        result["agreement"][name] = {
            "items_scored_by_both": len(pairs),
            "raw_agreement": proportion(
                sum(x == y for x, y in zip(a_labels, b_labels, strict=True)), len(pairs)
            ),
            "cohen_kappa": round(kappa, 3) if kappa is not None else None,
        }
        result["disagreements"] += [
            {"sheet": name, "item": list(k), "a": x, "b": y} for k, x, y in pairs if x != y
        ]
        agreed[name] = [(k, x) for k, x, y in pairs if x == y]

    systems: defaultdict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"support": [], "covered": [], "violated": []}
    )
    for (blind_id, _), label in agreed["claims.csv"]:
        if label != "n/a":
            systems[key_map[blind_id]["system"]]["support"].append(label)
    for (blind_id, _), label in agreed["coverage.csv"]:
        systems[key_map[blind_id]["system"]]["covered"].append(label)
    for (blind_id, _), label in agreed["must_not.csv"]:
        systems[key_map[blind_id]["system"]]["violated"].append(label)
    for system, values in sorted(systems.items()):
        result["by_system"][system] = {
            "evidence_support_full": proportion(values["support"].count("full"), len(values["support"])),
            "coverage": proportion(values["covered"].count("1"), len(values["covered"])),
            "must_not_violations": proportion(values["violated"].count("1"), len(values["violated"])),
            "note": "Agreed items only; resolve the listed disagreements and re-run to include them.",
        }
    result["by_system"] = dict(result["by_system"])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.score")
    parser.add_argument("scoring_dir", type=Path)
    parser.add_argument("scorer_a", type=Path)
    parser.add_argument("scorer_b", type=Path)
    args = parser.parse_args(argv)
    merged = merge(args.scoring_dir, args.scorer_a, args.scorer_b)
    out = args.scoring_dir / "human_scores.json"
    out.write_text(json.dumps(merged, indent=2), "utf-8")
    print(f"Wrote {out}: {len(merged['disagreements'])} disagreement(s) to adjudicate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
