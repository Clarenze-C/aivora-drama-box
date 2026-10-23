"""Contract-test configuration for the analytics lane (T027).

Puts the unit lane's support directory on ``sys.path`` (the sanctioned pattern)
so contract tests can share the lane's world scaffolding where needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_UNIT_ANALYTICS = Path(__file__).resolve().parents[2] / "unit" / "analytics"
if str(_UNIT_ANALYTICS) not in sys.path:
    sys.path.insert(0, str(_UNIT_ANALYTICS))
