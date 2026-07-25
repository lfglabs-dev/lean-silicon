"""Single import point for the LSC-1 transaction model.

``sim/lsc1_transaction.py`` is the normative executable companion to
``docs/LSC1_TRANSACTION_PROTOCOL.md``.  It is a top-level module inside
``sim/`` and the tests there import it as ``lsc1_transaction``.  Importing it
as ``sim.lsc1_transaction`` from here would create a second copy of the frozen
dataclasses, so ``Cell`` values built by the host would not compare equal to
``Cell`` values built by a test.  Bind the same top-level module instead.
"""

from __future__ import annotations

import pathlib
import sys

_SIM = pathlib.Path(__file__).resolve().parents[1] / "sim"
if str(_SIM) not in sys.path:
    sys.path.insert(0, str(_SIM))

import lsc1_transaction as protocol  # noqa: E402

__all__ = ["protocol"]
