"""Blind human scoring kit: python -m evaluation.blind <results-dir> [--claims-per-system N].

Produces, inside <results-dir>/scoring/:
- reports/<blind-id>.md      shuffled reports with the system identity removed
- claims.csv                 random sample of claims per system with the cited passage text
- coverage.csv               one row per report x must_cover point
- must_not.csv               one row per report x must_not condition
- INSTRUCTIONS.md            scoring rules for the human scorers
- KEY.json                   blind id → (case, system, repeat). Do NOT give this to scorers.

Scorers copy the CSVs, fill the empty score columns, and return them for
`python -m evaluation.score`.
"""

import argparse
import csv
import json
import random
import secrets
from collections import defaultdict
from pathlib import Path
from typing import Any

INSTRUCTIONS = """# Blind scoring instructions

You are scoring research reports produced by different systems. You do not know which system
produced which report, and you must not try to find out (do not open KEY.json).

Score independently of the other scorer. Write your scorer id in every row you fill.

## claims.csv: evidence support
For each row, read the claim and the cited passage(s) only. Set `support` to:
- `full`: every factual part of the claim is stated in the cited passage(s);
- `partial`: some of it is supported, some is not;
- `none`: the passage does not support the claim, or no passage is cited for a factual claim.
For claims labelled `unknown` or `recommendation`, set `support` to `n/a`.
Set `uncertainty_ok` to `1` if conflicts, gaps or unknowns are labelled as such rather than
filled in, else `0` (leave empty if not applicable).

## coverage.csv
Open the report (scoring/reports/<blind_id>.md). Set `covered` to `1` if the point is addressed
with a citation or an explicit "unknown", else `0`.

## must_not.csv
Set `violated` to `1` if the report shows the listed behaviour, else `0`. Any violation fails
the case.

## Time
In coverage.csv, record `minutes` once per report (first row): how long you needed to decide
whether you would approve the report.
"""


def blind(results_dir: Path, claims_per_system: int = 30, seed: int | None = None) -> Path:
    rng = random.Random(seed if seed is not None else secrets.randbits(32))
    scoring = results_dir / "scoring"
    (scoring / "reports").mkdir(parents=True, exist_ok=True)
    records = [
        json.loads(line) for line in (results_dir / "runs.jsonl").read_text("utf-8").splitlines() if line
    ]
    keys = [r["key"] for r in records if (results_dir / "reports" / f"{r['key']}.md").exists()]
    rng.shuffle(keys)
    key_map: dict[str, dict[str, Any]] = {}
    by_key = {r["key"]: r for r in records}
    for index, key in enumerate(keys, 1):
        blind_id = f"R{index:03d}"
        record = by_key[key]
        key_map[blind_id] = {
            "key": key,
            "case_id": record["case_id"],
            "system": record["system"],
            "repeat": record["repeat"],
        }
        text = (results_dir / "reports" / f"{key}.md").read_text("utf-8")
        (scoring / "reports" / f"{blind_id}.md").write_text(text, "utf-8")

    claims_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    coverage_rows: list[dict[str, str]] = []
    must_not_rows: list[dict[str, str]] = []
    for blind_id, entry in key_map.items():
        artifact = json.loads((results_dir / "artifacts" / f"{entry['key']}.json").read_text("utf-8"))
        report = artifact.get("report") or {"sections": []}
        passages = artifact.get("cited_passages", {})
        for section in report["sections"]:
            for claim in section["claims"]:
                cited = "\n---\n".join(
                    f"[{e}] {passages[e]['text']}" for e in claim["evidence_ids"] if e in passages
                )
                claims_rows[entry["system"]].append(
                    {
                        "blind_id": blind_id,
                        "claim_id": claim["claim_id"],
                        "kind": claim["kind"],
                        "claim": claim["text"],
                        "cited_passages": cited or "(none)",
                        "support": "",
                        "uncertainty_ok": "",
                        "scorer": "",
                    }
                )
        for point in artifact.get("must_cover", []):
            coverage_rows.append(
                {"blind_id": blind_id, "point": point, "covered": "", "minutes": "", "scorer": ""}
            )
        for condition in artifact.get("must_not", []):
            must_not_rows.append({"blind_id": blind_id, "condition": condition, "violated": "", "scorer": ""})

    sampled: list[dict[str, str]] = []
    for rows in claims_rows.values():
        sampled += rng.sample(rows, min(claims_per_system, len(rows)))
    rng.shuffle(sampled)
    for name, rows in (
        ("claims.csv", sampled),
        ("coverage.csv", coverage_rows),
        ("must_not.csv", must_not_rows),
    ):
        write_csv(scoring / name, rows)
    (scoring / "INSTRUCTIONS.md").write_text(INSTRUCTIONS, "utf-8")
    (scoring / "KEY.json").write_text(json.dumps(key_map, indent=2), "utf-8")
    return scoring


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not rows:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.blind")
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("--claims-per-system", type=int, default=30)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)
    out = blind(args.results_dir, args.claims_per_system, args.seed)
    print(f"Scoring kit written to {out}. Give scorers everything except KEY.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
