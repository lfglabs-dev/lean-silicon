"""Host-side byte/cycle contract model for the MinCore lane.

This is deliberately a *transport* model, not a second implementation of the
ALU.  It wraps the cycle model and records only committed transfers.  In
particular, synchronous ``ABORT`` wins over a same-edge ready/valid transfer:
pins may indicate a potential handshake combinationally, but the RTL discards
it at the clock edge.  A bridge must therefore use ``not abort`` when it
accounts for committed bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from cycle_model import Pins, StreamALUCycleModel


@dataclass(frozen=True)
class CycleRecord:
    """Observable pins and transfers committed at one rising edge."""

    pins: Pins
    rx_committed: bool
    tx_committed: bool


class ProtocolLane:
    """A resettable byte-lane contract wrapper around ``StreamALUCycleModel``.

    ``reset_n`` represents the top-level synchronous active-low reset sampled
    at this edge.  The Python cycle model begins in the reset state, so a reset
    edge replaces it with a fresh instance.  This mirrors the architectural
    state visible at the wrapper boundary (IDLE, no fault, no response).
    """

    def __init__(self) -> None:
        self.core = StreamALUCycleModel()

    def step(
        self,
        *,
        rx_data: int = 0,
        rx_valid: bool = False,
        tx_ready: bool = False,
        abort: bool = False,
        reset_n: bool = True,
    ) -> CycleRecord:
        if not reset_n:
            self.core = StreamALUCycleModel()
            pins, _ = self.core.combinational(
                rx_data=rx_data, rx_valid=rx_valid, tx_ready=tx_ready
            )
            return CycleRecord(pins, False, False)

        pins = self.core.step(
            rx_data=rx_data,
            rx_valid=rx_valid,
            tx_ready=tx_ready,
            abort=abort,
        )
        # abort has priority in the sequential RTL; no candidate transfer is
        # architecturally accepted or produced on that edge.
        return CycleRecord(
            pins,
            rx_committed=bool(rx_valid and pins.rx_ready and not abort),
            tx_committed=bool(pins.tx_valid and tx_ready and not abort),
        )
