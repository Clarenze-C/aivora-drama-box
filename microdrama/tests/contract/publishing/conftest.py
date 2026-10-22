"""Contract-test configuration for the publishing lane (T020).

Puts the unit lane's ``publishing_support`` module on ``sys.path`` so the contract
tests share one source of truth for the World scaffolding (the sanctioned pattern from
``tests/contract/references/conftest.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

_UNIT_SUPPORT = Path(__file__).resolve().parents[2] / "unit" / "publishing"
if str(_UNIT_SUPPORT) not in sys.path:
    sys.path.insert(0, str(_UNIT_SUPPORT))
