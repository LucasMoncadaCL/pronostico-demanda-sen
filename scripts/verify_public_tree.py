"""Check that Git-tracked files respect the public data-distribution boundary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

# Raw and derived data containers are not part of the public portfolio tree.
BLOCKED_SUFFIXES = {
    ".arrow",
    ".csv",
    ".feather",
    ".h5",
    ".hdf5",
    ".joblib",
    ".ndjson",
    ".npy",
    ".npz",
    ".parquet",
    ".pkl",
    ".pickle",
    ".tsv",
    ".xls",
    ".xlsx",
    ".zip",
}
RESERVED_PREFIXES = (
    "archive/",
    "data/audit/",
    "data/audits/",
    "data/external/",
    "data/interim/",
    "data/original/",
    "data/originals/",
    "data/private/",
    "data/processed/",
    "data/raw/",
    "data/source/",
    "data/source-data/",
    "data/source_data/",
    "evidence/",
)
ALLOWED_DATA_FILES = {"data/README.md"}


def find_policy_violations(paths: Iterable[str]) -> list[str]:
    """Return a message for each tracked path outside the public data policy."""
    violations = []
    for original_path in paths:
        path = original_path.replace("\\", "/").lstrip("./")
        lowered = path.casefold()
        name = Path(path).name.casefold()

        if lowered.startswith("data/") and path not in ALLOWED_DATA_FILES:
            violations.append(f"{path}: files under data/ are not approved for this public tree")
        if any(lowered.startswith(prefix) for prefix in RESERVED_PREFIXES):
            violations.append(f"{path}: reserved source-data/evidence location")
        if Path(path).suffix.casefold() in BLOCKED_SUFFIXES:
            violations.append(f"{path}: restricted data/archive format")
        if name.startswith(".env") and name != ".env.example":
            violations.append(f"{path}: environment files are not approved for publication")

    return violations


def tracked_paths(root: Path = ROOT) -> list[str]:
    """Read the Git index paths that will be included in the next commit."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [entry.decode("utf-8") for entry in result.stdout.split(b"\0") if entry]


def main() -> int:
    violations = find_policy_violations(tracked_paths())
    if violations:
        print("Public tree policy failed:")
        for violation in violations:
            print(f"- {violation}")
        return 1

    print("Public tree policy passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
