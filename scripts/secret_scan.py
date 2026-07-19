#!/usr/bin/env python3
import re
import sys
from pathlib import Path

BLOCKED_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|token|secret)\s*=\s*['\"][A-Za-z0-9_.:/+@-]{8,}['\"]"),
    re.compile(r"(?i)\b(imei|imsi|iccid|subscriber_number)\b\s*[:=]\s*['\"]?\d{10,}"),
]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "references"}


def iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "secret_scan.py":
            continue
        if set(path.parts) & SKIP_DIRS:
            continue
        yield path


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    failures: list[str] = []
    for path in iter_files(root):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for pattern in BLOCKED_PATTERNS:
            if pattern.search(text):
                failures.append(str(path))
                break
    if failures:
        print("Potential secret/private modem identifier patterns found:")
        for failure in failures:
            print(f" - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
