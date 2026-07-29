# SPDX-License-Identifier: Apache-2.0
import cocotb
from cocotb.triggers import RisingEdge


async def cycles(dut, count):
    for _ in range(count):
        await RisingEdge(dut.clk)


@cocotb.test()
async def tiny_tapeout_lane_reset_enable_and_handshake(dut):
    """Exercise the physical pin contract in both RTL and GL simulation."""
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.ena.value = 0
    dut.rst_n.value = 0
    await cycles(dut, 4)

    assert int(dut.uo_out.value) == 0
    assert int(dut.uio_out.value) == 0
    assert int(dut.uio_oe.value) == 0

    dut.ena.value = 1
    await cycles(dut, 2)
    dut.rst_n.value = 1
    await cycles(dut, 2)

    # Fixed directions: REQUEST_READY, RESPONSE_VALID, BUSY, FAULT and
    # DONE_PULSE are outputs; the other uio pins remain inputs.
    assert int(dut.uio_oe.value) == 0b10110110
    assert (int(dut.uio_out.value) >> 1) & 1 == 1

    # A request byte is accepted only when REQUEST_VALID and REQUEST_READY meet.
    dut.ui_in.value = 0xA5
    dut.uio_in.value = 1 << 0
    await RisingEdge(dut.clk)
    dut.uio_in.value = 0
    await cycles(dut, 1)

    # Deselecting clamps all externally visible drive paths, independently of
    # the packet parser state reached by the deliberately incomplete frame.
    dut.ena.value = 0
    await cycles(dut, 1)
    assert int(dut.uo_out.value) == 0
    assert int(dut.uio_out.value) == 0
    assert int(dut.uio_oe.value) == 0
