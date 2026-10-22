"""Contract-test configuration for the community lane (T025).

Puts the unit lane's support directory on ``sys.path`` (the sanctioned pattern
from ``tests/contract/publishing/conftest.py``) so contract tests can share the
lane's world scaffolding where needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_UNIT_COMMUNITY = Path(__file__).resolve().parents[2] / "unit" / "community"
if str(_UNIT_COMMUNITY) not in sys.path:
    sys.path.insert(0, str(_UNIT_COMMUNITY))
