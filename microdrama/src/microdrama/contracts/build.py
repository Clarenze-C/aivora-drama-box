"""``make contracts`` / ``make contracts-check`` entry point.

Generates JSON Schemas and example payloads under ``microdrama/contracts/`` from
the Python contract models, validates every example (valid ones must pass,
invalid ones must fail), and in ``--check`` mode fails when the committed files
drift from the source.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from microdrama.contracts import CONTRACT_VERSION

ROOT = Path(__file__).resolve().parents[3] / "contracts"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.parse_args(argv)
    print(f"contracts {CONTRACT_VERSION}: scaffold only (no schemas until T002)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
