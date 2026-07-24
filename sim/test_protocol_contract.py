"""Deterministic adversarial vectors for the byte/cycle transport contract."""

from __future__ import annotations

import unittest

from model import Command
from protocol_contract import ProtocolLane


class ProtocolContractTests(unittest.TestCase):
    def test_set_backpressure_holds_data_and_refuses_input(self) -> None:
        lane = ProtocolLane()
        lane.step(rx_data=Command.SET128, rx_valid=True)
        first = lane.step(rx_data=0x5A, rx_valid=True, tx_ready=False)
        second = lane.step(rx_data=0x5A, rx_valid=True, tx_ready=False)
        self.assertTrue(first.pins.tx_valid)
        self.assertFalse(first.pins.rx_ready)
        self.assertFalse(first.rx_committed)
        self.assertEqual(first.pins.tx_data, 0x5A)
        self.assertEqual(second.pins.tx_data, 0x5A)
        accepted = lane.step(rx_data=0x5A, rx_valid=True, tx_ready=True)
        self.assertTrue(accepted.rx_committed)
        self.assertTrue(accepted.tx_committed)

    def test_status_holds_each_byte_under_backpressure(self) -> None:
        lane = ProtocolLane()
        lane.step(rx_data=Command.STATUS, rx_valid=True)
        stalled = lane.step(tx_ready=False)
        again = lane.step(tx_ready=False)
        self.assertTrue(stalled.pins.tx_valid)
        self.assertEqual(stalled.pins.tx_data, 0x01)
        self.assertEqual(again.pins.tx_data, 0x01)
        self.assertFalse(stalled.tx_committed)

    def test_abort_discards_candidate_stream_transfer_and_sets_fault(self) -> None:
        lane = ProtocolLane()
        lane.step(rx_data=Command.SET128, rx_valid=True)
        edge = lane.step(rx_data=0xC3, rx_valid=True, tx_ready=True, abort=True)
        self.assertTrue(edge.pins.rx_ready)
        self.assertTrue(edge.pins.tx_valid)
        self.assertFalse(edge.rx_committed)
        self.assertFalse(edge.tx_committed)
        idle = lane.step()
        self.assertTrue(idle.pins.rx_ready)
        self.assertFalse(idle.pins.busy)
        self.assertTrue(idle.pins.fault)

    def test_reset_discards_transaction_and_clears_fault(self) -> None:
        lane = ProtocolLane()
        lane.step(rx_data=0x99, rx_valid=True)
        lane.step(tx_ready=True)
        self.assertTrue(lane.step().pins.fault)
        reset = lane.step(rx_data=Command.STATUS, rx_valid=True, reset_n=False)
        self.assertFalse(reset.rx_committed)
        self.assertFalse(reset.tx_committed)
        after = lane.step()
        self.assertTrue(after.pins.rx_ready)
        self.assertFalse(after.pins.fault)
        self.assertFalse(after.pins.busy)

    def test_unknown_command_has_exactly_one_error_byte(self) -> None:
        lane = ProtocolLane()
        lane.step(rx_data=0x99, rx_valid=True)
        stalled = lane.step(tx_ready=False)
        self.assertTrue(stalled.pins.tx_valid)
        self.assertEqual(stalled.pins.tx_data, 0xE0)
        self.assertFalse(stalled.tx_committed)
        sent = lane.step(tx_ready=True)
        self.assertTrue(sent.tx_committed)
        self.assertTrue(sent.pins.fault)
        self.assertFalse(lane.step().pins.busy)


if __name__ == "__main__":
    unittest.main()
