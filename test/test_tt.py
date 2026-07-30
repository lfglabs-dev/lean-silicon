# SPDX-License-Identifier: Apache-2.0
import random

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, Timer


RX_VALID = 1 << 0
RX_READY = 1 << 1
TX_VALID = 1 << 2
TX_READY = 1 << 3
BUSY = 1 << 4
FAULT = 1 << 5
DONE = 1 << 7
OUTPUT_ENABLES = 0b10110110


async def tick(dut, count=1):
    for _ in range(count):
        await RisingEdge(dut.clk)
        await ReadOnly()
        await Timer(1, unit="ps")


def bit(dut, mask):
    return bool(int(dut.uio_out.value) & mask)


async def reset(dut):
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.ena.value = 1
    dut.rst_n.value = 0
    await tick(dut, 3)
    dut.rst_n.value = 1
    await tick(dut)
    assert bit(dut, RX_READY)


async def send(dut, byte, stall=0):
    dut.ui_in.value = byte
    dut.uio_in.value = 0
    for _ in range(stall):
        await tick(dut)
    dut.uio_in.value = RX_VALID
    waits = 0
    while not bit(dut, RX_READY):
        await tick(dut)
        waits += 1
        assert waits < 400, (
            f"RX_READY timeout sending 0x{byte:02x}; "
            f"state={int(dut.dut.core.state.value)} "
            f"index={int(dut.dut.core.byte_index.value)} "
            f"saved=0x{int(dut.dut.core.saved_byte.value):02x}"
        )
    await tick(dut)
    dut.uio_in.value = 0


async def receive(dut, stall=0):
    waits = 0
    while not bit(dut, TX_VALID):
        await tick(dut)
        waits += 1
        assert waits < 400, "TX_VALID timeout"
    held = int(dut.uo_out.value)
    for _ in range(stall):
        assert bit(dut, TX_VALID)
        assert int(dut.uo_out.value) == held
        await tick(dut)
    dut.uio_in.value = TX_READY
    value = int(dut.uo_out.value)
    await tick(dut)
    done = bit(dut, DONE)
    dut.uio_in.value = 0
    return value, done


async def transact(dut, opcode, payload, expected, rng):
    await send(dut, opcode)
    assert bit(dut, BUSY)
    output = []
    done_count = 0
    for byte in payload:
        await send(dut, byte, rng.randrange(3))
        if bit(dut, TX_VALID):
            value, done = await receive(dut, rng.randrange(5))
            output.append(value)
            done_count += done
    while len(output) < len(expected):
        value, done = await receive(dut, rng.randrange(5))
        output.append(value)
        done_count += done
    assert bytes(output) == expected
    assert done_count == 1
    await tick(dut)
    assert not bit(dut, DONE)
    assert not bit(dut, BUSY)


def gf128_mul(a, b):
    product = 0
    for _ in range(128):
        if b & 1:
            product ^= a
        b >>= 1
        a = ((a << 1) & ((1 << 128) - 1)) ^ (0x87 if a >> 127 else 0)
    return product


@cocotb.test()
async def lsc1u_all_retained_operations(dut):
    rng = random.Random(0x1C51)
    await reset(dut)
    for _ in range(8):
        a = bytes(rng.getrandbits(8) for _ in range(16))
        b = bytes(rng.getrandbits(8) for _ in range(16))
        xor_payload = b"".join(bytes((x, y)) for x, y in zip(a, b))
        await transact(dut, 0x01, xor_payload,
                       bytes(x ^ y for x, y in zip(a, b)), rng)
        await transact(dut, 0x03, a, a, rng)
        product = gf128_mul(int.from_bytes(a, "little"),
                            int.from_bytes(b, "little"))
        await transact(dut, 0x02, a + b,
                       product.to_bytes(16, "little"), rng)


@cocotb.test()
async def lsc1u_reset_ena_framing_and_backpressure(dut):
    await reset(dut)

    # A payload byte without an accepted opcode is itself an unsupported opcode.
    await send(dut, 0x44)
    value, done = await receive(dut, 3)
    assert (value, done) == (0xE0, True)
    assert not bit(dut, FAULT)

    # Freeze a partial XOR while deselected; no pin is driven and no byte fires.
    await send(dut, 0x01)
    await send(dut, 0xA5)
    dut.ui_in.value = 0x5A
    dut.uio_in.value = RX_VALID | TX_READY
    dut.ena.value = 0
    await tick(dut, 4)
    assert int(dut.uo_out.value) == 0
    assert int(dut.uio_out.value) == 0
    assert int(dut.uio_oe.value) == 0
    dut.ena.value = 1
    await tick(dut)
    assert int(dut.uio_oe.value) == OUTPUT_ENABLES
    dut.uio_in.value = 0
    value, done = await receive(dut, 4)
    assert value == 0xFF and not done

    # Reset cancels the remaining fixed-width frame and exposes command ready.
    dut.rst_n.value = 0
    dut.uio_in.value = RX_VALID | TX_READY
    await tick(dut)
    assert not bit(dut, TX_VALID | DONE | BUSY | FAULT)
    dut.rst_n.value = 1
    dut.uio_in.value = 0
    await tick(dut)
    assert bit(dut, RX_READY)

    # Output stability under a long stall is mutation-sensitive.
    await send(dut, 0x03)
    await send(dut, 0xC3)
    assert bit(dut, TX_VALID)
    for value in (0x00, 0xFF, 0x5A, 0x81):
        dut.ui_in.value = value
        await tick(dut)
        assert bit(dut, TX_VALID)
        assert int(dut.uo_out.value) == 0xC3


@cocotb.test()
async def lsc1u_little_endian_polynomial_vectors(dut):
    await reset(dut)
    rng = random.Random(1)
    one = (1).to_bytes(16, "little")
    top = (1 << 127).to_bytes(16, "little")
    two = (2).to_bytes(16, "little")
    await transact(dut, 0x02, one + top, top, rng)
    await transact(dut, 0x02, top + two, (0x87).to_bytes(16, "little"), rng)
