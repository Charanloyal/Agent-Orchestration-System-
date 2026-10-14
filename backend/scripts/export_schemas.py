"""Write JSON Schemas for all contracts to docs/contracts/.

Run from backend/:  python -m scripts.export_schemas
tests/test_contract_schemas.py fails if the checked-in files drift from the models.
"""

import json
from pathlib import Path

from app.contracts import SCHEMA_MODELS

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "contracts"


def render_schemas() -> dict[str, str]:
    return {
        f"{name}.schema.json": json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        for name, model in SCHEMA_MODELS.items()
    }


def main() -> None:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for filename, content in render_schemas().items():
        (SCHEMA_DIR / filename).write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {filename}")


if __name__ == "__main__":
    main()
