# SPDX-License-Identifier: Apache-2.0
import zlib

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, Timer


REQUEST_VALID = 1 << 0
REQUEST_READY = 1 << 1
RESPONSE_VALID = 1 << 2
RESPONSE_READY = 1 << 3
ABORT = 1 << 6
OUTPUT_ENABLES = 0b10110110


async def cycles(dut, count):
    for _ in range(count):
        await RisingEdge(dut.clk)
        await ReadOnly()
        await Timer(1, unit="ps")


def uio_bit(dut, bit):
    return (int(dut.uio_out.value) >> bit) & 1


def status_request():
    """A complete v1 STATUS_QUERY frame, including its wire CRC."""
    body = bytes((0xA1, 0x01, 0x13, 0x00, 0x00, 0x00))
    return body + zlib.crc32(body).to_bytes(4, "little")


async def send_bytes(dut, payload):
    for byte in payload:
        dut.ui_in.value = byte
        dut.uio_in.value = REQUEST_VALID
        while not uio_bit(dut, 1):
            await RisingEdge(dut.clk)
            await ReadOnly()
            await Timer(1, unit="ps")
        await RisingEdge(dut.clk)
        await ReadOnly()
        await Timer(1, unit="ps")
        dut.uio_in.value = 0


async def wait_for_response(dut):
    while not uio_bit(dut, 2):
        await RisingEdge(dut.clk)
        await ReadOnly()
        await Timer(1, unit="ps")


async def consume_status_response(dut):
    """Consume and check the complete 20-byte STATUS_QUERY response."""
    response = []
    dut.uio_in.value = RESPONSE_READY
    while len(response) < 29:
        assert uio_bit(dut, 2), "response_valid dropped before the full response"
        response.append(int(dut.uo_out.value))
        await RisingEdge(dut.clk)
        await ReadOnly()
        await Timer(1, unit="ps")
    dut.uio_in.value = 0
    assert response[0:5] == [0x5A, 0x01, 0x03, 20, 0]
    assert zlib.crc32(bytes(response[:-4])) == int.from_bytes(
        bytes(response[-4:]), "little"
    )


@cocotb.test()
async def tiny_tapeout_lane_reset_enable_and_handshake(dut):
    """Mutation-sensitive wrapper tests for ready/valid, abort, reset, and ena."""
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
    assert int(dut.uio_oe.value) == OUTPUT_ENABLES
    assert uio_bit(dut, 1) == 1

    # ena must block an asserted request, then admit the exact same SOF once
    # selected. This detects removal of the wrapper's input handshake mask.
    frame = status_request()
    dut.ena.value = 0
    dut.ui_in.value = frame[0]
    dut.uio_in.value = REQUEST_VALID
    await cycles(dut, 2)
    assert int(dut.uo_out.value) == 0
    assert int(dut.uio_out.value) == 0
    assert int(dut.uio_oe.value) == 0
    dut.ena.value = 1
    await RisingEdge(dut.clk)
    await ReadOnly()
    await Timer(1, unit="ps")
    dut.uio_in.value = 0
    await send_bytes(dut, frame[1:])

    # Hold a real response under backpressure. Deselect while RESPONSE_VALID
    # remains asserted: outputs must clamp and RESPONSE_READY must not leak to
    # the core; reselecting must expose the unchanged response byte.
    await wait_for_response(dut)
    held_byte = int(dut.uo_out.value)
    held_uio = int(dut.uio_out.value)
    assert held_uio & RESPONSE_VALID
    dut.uio_in.value = 0
    await cycles(dut, 3)
    assert int(dut.uo_out.value) == held_byte
    assert int(dut.uio_out.value) == held_uio
    dut.ena.value = 0
    dut.uio_in.value = REQUEST_VALID | RESPONSE_READY
    await cycles(dut, 2)
    assert int(dut.uo_out.value) == 0
    assert int(dut.uio_out.value) == 0
    assert int(dut.uio_oe.value) == 0
    dut.ena.value = 1
    dut.uio_in.value = 0
    await cycles(dut, 1)
    assert uio_bit(dut, 2) == 1
    assert int(dut.uo_out.value) == held_byte
    await consume_status_response(dut)

    # Reset during an active response must discard the transfer even when both
    # request and response inputs are asserted.
    await send_bytes(dut, status_request())
    await wait_for_response(dut)
    dut.uio_in.value = REQUEST_VALID | RESPONSE_READY
    await RisingEdge(dut.clk)
    await ReadOnly()
    await Timer(1, unit="ps")
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    await Timer(1, unit="ps")
    assert uio_bit(dut, 2) == 0
    dut.uio_in.value = 0
    dut.rst_n.value = 1
    await cycles(dut, 2)
    assert uio_bit(dut, 2) == 0

    # ABORT has the same transfer-cancellation requirement, but also asserts
    # the core fault indication after the aborted response is gone.
    await send_bytes(dut, status_request())
    await wait_for_response(dut)
    dut.uio_in.value = REQUEST_VALID | RESPONSE_READY | ABORT
    await RisingEdge(dut.clk)
    await ReadOnly()
    await Timer(1, unit="ps")
    dut.uio_in.value = 0
    await RisingEdge(dut.clk)
    await ReadOnly()
    await Timer(1, unit="ps")
    assert uio_bit(dut, 2) == 0
    assert uio_bit(dut, 5) == 1
