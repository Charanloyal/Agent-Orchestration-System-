"""Docker HEALTHCHECK for every role of the image (ADR 0018, finding G4).

    python -m app.healthcheck

- The web server, if this container runs one, must answer GET /healthz on $PORT.
- A worker, if this container runs one, must have marked itself alive recently
  (AOS_WORKER_ALIVE_FILE, at most AOS_WORKER_ALIVE_MAX_AGE_SECONDS old).

The web + worker topology runs one role per container; the single-process topology runs
both, and both are checked. Exit 0 when healthy, 1 otherwise. Standard library only, so it
starts fast and needs no database.
"""

import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def check(port: int, alive_file: Path | None, *, max_age: float) -> tuple[bool, str]:
    parts: list[str] = []
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3) as response:
            if response.status != 200:
                return False, f"web /healthz -> {response.status}"
        parts.append("web ok")
    except urllib.error.HTTPError as exc:
        return False, f"web /healthz -> {exc.code}"
    except OSError:
        pass  # no web server in this container
    if alive_file is not None and alive_file.exists():
        age = time.time() - alive_file.stat().st_mtime
        if age > max_age:
            return False, f"worker last alive {age:.0f} s ago"
        parts.append("worker ok")
    if not parts:
        return False, "neither the web server nor a worker is running"
    return True, ", ".join(parts)


def main() -> int:
    alive = os.environ.get("AOS_WORKER_ALIVE_FILE")
    ok, reason = check(
        int(os.environ.get("PORT", "10000")),
        Path(alive) if alive else None,
        max_age=float(os.environ.get("AOS_WORKER_ALIVE_MAX_AGE_SECONDS", "120")),
    )
    print(reason)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
