"""Contract-test configuration for the references lane (T011).

Puts the unit lane's ``references_support`` module on ``sys.path`` so the contract
tests share one source of truth for the World scaffolding instead of duplicating it
(the same pattern the story lane solved with a local support file).
"""

from __future__ import annotations

import sys
from pathlib import Path

_UNIT_SUPPORT = Path(__file__).resolve().parents[2] / "unit" / "references"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))
