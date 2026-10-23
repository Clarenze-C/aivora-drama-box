"""Contract-test configuration for the workers lane (T028).

Puts the unit lane's support directory on ``sys.path`` (the sanctioned pattern)
so contract tests can share the lane's world scaffolding where needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_UNIT_WORKERS = Path(__file__).resolve().parents[2] / "unit" / "workers"
if str(_UNIT_WORKERS) not in sys.path:
    sys.path.insert(0, str(_UNIT_WORKERS))
