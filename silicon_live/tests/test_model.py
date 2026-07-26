from pathlib import Path
import asyncio
import pytest

from silicon_live.app import SiliconLive
from silicon_live.model import EventKind, MASK128, Replay, events_for, fault_event, load_evidence
from silicon_live.transport import FakeSerial, HostRuntimeTransport, encode_request


def test_loader_preserves_full_u128(tmp_path: Path):
    evidence = load_evidence()
    assert evidence.steps[0].result == 3
    assert all(0 <= value <= MASK128 for value in evidence.expected_memory)
    assert len(evidence.steps[0].response) == 16


def test_structured_event_pipeline():
    events = events_for(load_evidence().steps[2])
    assert [e.kind for e in events] == [
        EventKind.PREPARE, EventKind.UART_SEND, EventKind.FPGA_COMPUTE,
        EventKind.RESPONSE, EventKind.VALIDATE, EventKind.MEMORY_WRITE,
    ]
    assert {e.actor for e in events} == {"HOST", "FPGA"}


def test_replay_prefix_not_pass():
    replay = Replay(load_evidence())
    while replay.advance():
        pass
    assert replay.terminal == "PREFIX MATCH ✓"
    assert "PASS" not in replay.terminal
    assert replay.cursor == 12
    assert replay.memory[11] == 0x8000


def test_mismatch_is_error():
    evidence = load_evidence()
    step = evidence.steps[0]
    evidence.steps[0] = type(step)(step.pc, step.kind, step.addresses, step.inputs,
                                  step.result, step.request, b"bad")
    replay = Replay(evidence)
    assert replay.advance() is False
    assert replay.terminal == "MISMATCH"


def test_timeout_and_protocol_fault_events_are_explicit():
    assert fault_event(TimeoutError("late"), 4).message.startswith("TIMEOUT:")
    assert fault_event(ValueError("bad frame"), 4).message.startswith("PROTOCOL FAULT:")


def test_fake_serial_and_request():
    fake = FakeSerial(b"\x01" * 16)
    request = encode_request("Set", (3,))
    assert fake.write(request) == 17
    assert request[0] == 0x03
    assert fake.read(16) == b"\x01" * 16
    assert bytes(fake.written) == request


def test_xor_request_uses_historical_interleaving():
    request = encode_request("Xor", (0x0102, 0x0304))
    assert len(request) == 33 and request[0] == 0x01
    assert request[1:5] == bytes([0x02, 0x04, 0x01, 0x03])


def test_host_runtime_adapter_preserves_128_bits():
    model = HostRuntimeTransport()
    maximum = MASK128.to_bytes(16, "little")
    request, response = model.exchange("xor", a=maximum, b=b"\0" * 16)
    assert len(request) == 33
    assert response == maximum


@pytest.mark.asyncio
async def test_pilot_navigation_progression_and_narrow():
    app = SiliconLive(auto_run=False)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("s", "s")
        assert app.replay.cursor == 2
        await pilot.press("+")
        assert app.speed == 2.0
        assert app._timer.interval == pytest.approx(.225)
        await pilot.resize_terminal(76, 42)
        await pilot.pause()
        assert app.screen.has_class("narrow")
        await pilot.press("r")
        assert app.replay.cursor == 0
