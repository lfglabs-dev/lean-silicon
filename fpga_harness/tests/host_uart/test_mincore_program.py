import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from fpga_harness.host.mincore_program import (HardwareMismatch, MinCoreProgramRunner,
    compare_upstream_prefix)
from fpga_harness.host.mincore_uart import encode_request
from host import lean_compiler_adapter as adapter
from host.errors import WriteOnceViolation
from host.memory import HostMemory
from host.protocol import protocol

ARTIFACT = ROOT / "host" / "fixtures" / "assert_set_xor_mul.program.json"


class OracleDriver:
    def __init__(self):
        self.operations = []

    def exchange(self, operation, *, a=b"", b=b"", value=b""):
        self.operations.append(operation)
        if operation == "status":
            return b"\x7e", bytes.fromhex("01010f08")
        if operation == "set":
            result = value
        elif operation == "xor":
            result = bytes(left ^ right for left, right in zip(a, b))
        elif operation == "mul":
            product = protocol.field_mul(int.from_bytes(a, "little"), int.from_bytes(b, "little"))
            result = product.to_bytes(16, "little")
        else:
            raise AssertionError(operation)
        return encode_request(operation, a=a, b=b, value=value), result


def program(*operations):
    sentinel = adapter.Operation(len(operations), "Set", {"o": 0, "k": 0})
    return adapter.Program(
        operations=tuple(operations) + (sentinel,), pc0=0, fp0=0, fn_ranges=(),
        source="", upstream_sha=adapter.FROZEN_LEANVM_B, disassembly="",
        upstream_execution=None,
    )


class MinCoreProgramTests(unittest.TestCase):
    def test_checked_in_program_runs_twelve_hardware_operations_then_stops_at_jump(self):
        compiled, driver = adapter.load(ARTIFACT), OracleDriver()
        runner = MinCoreProgramRunner(compiled, driver)
        run = runner.run()
        self.assertEqual((run.terminal, run.pc, len(run.steps)), ("unsupported", 12, 12))
        self.assertIn("Jump", run.reason)
        self.assertEqual(driver.operations[0], "status")
        self.assertEqual(driver.operations[1:], [
            "set", "set", "xor", "set", "xor", "set",
            "mul", "set", "xor", "set", "set", "set",
        ])
        comparison = compare_upstream_prefix(compiled, runner, run)
        self.assertEqual(comparison["result"], "PREFIX_MATCH")
        self.assertEqual(comparison["compared_memory_addresses"], list(range(12)))
        self.assertEqual(comparison["missing_upstream_addresses"], [])
        self.assertEqual(comparison["mismatches"], [])

    def test_wrong_hardware_result_is_rejected_before_memory_changes(self):
        class Wrong(OracleDriver):
            def exchange(self, operation, **values):
                request, response = super().exchange(operation, **values)
                return request, (b"\xff" * 16 if operation == "xor" else response)

        compiled = program(
            adapter.Operation(0, "Set", {"o": 2, "k": 3}),
            adapter.Operation(1, "Set", {"o": 3, "k": 5}),
            adapter.Operation(2, "Xor", {"a": 2, "b": 3, "c": 4}),
        )
        runner = MinCoreProgramRunner(compiled, Wrong())
        runner.step(); runner.step()
        with self.assertRaisesRegex(HardwareMismatch, "returned"):
            runner.step()
        self.assertFalse(runner.memory.written(4))
        self.assertEqual(runner.pc, 2)

    def test_write_conflict_is_rejected_before_second_exchange(self):
        compiled = program(
            adapter.Operation(0, "Set", {"o": 2, "k": 3}),
            adapter.Operation(1, "Set", {"o": 2, "k": 4}),
        )
        driver = OracleDriver()
        runner = MinCoreProgramRunner(compiled, driver)
        runner.step()
        with self.assertRaises(WriteOnceViolation):
            runner.step()
        self.assertEqual(driver.operations, ["set"])

    def test_unwritten_operand_stops_without_sending_instruction(self):
        compiled = program(adapter.Operation(0, "Xor", {"a": 2, "b": 3, "c": 4}))
        driver = OracleDriver()
        runner = MinCoreProgramRunner(compiled, driver)
        run = runner.run(check_status=False)
        self.assertEqual(run.terminal, "unsupported")
        self.assertIn("unwritten", run.reason)
        self.assertEqual(driver.operations, [])
        self.assertEqual(runner.memory.cells, {0: 1, 1: 0})


if __name__ == "__main__":
    unittest.main()
