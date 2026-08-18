"""Executable host/model prerequisites for the external BLAKE3 service."""

from __future__ import annotations

import pathlib
import random
import subprocess
import unittest

from host.blake3_service import (
    ModelServiceAdapter,
    ServiceInfrastructureError,
    ServiceKey,
    ServiceRequired,
    ServiceResponse,
    ServiceSemanticError,
    ServiceStatus,
    compress,
)
from host.protocol import protocol

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools" / "blake3_reference" / "Cargo.toml"
BINARY = ROOT / "tools" / "blake3_reference" / "target" / "debug" / "lsc1-blake3-reference"
SEED = 0xB1A3E3


def exchange(endpoint, frame, *, rx_gaps=None, tx_gaps=None):
    raw, _ = protocol.drive(
        endpoint, frame.encode(), rx_gaps=rx_gaps, tx_gaps=tx_gaps,
    )
    return protocol.decode_response(raw)


def blake3_request(txn_id=1, *, out=(protocol.ABSENT, protocol.ABSENT)):
    return protocol.build_blake3(
        txn_id=txn_id, pc=2, fp=64,
        profile=protocol.Profile.INTERPRETER_COMPAT,
        message_offsets=(0, 1, 2, 3), cv_offset=8, out_offset=10,
        metadata=64 << 64,
        message_cells=tuple(protocol.Cell(True, i) for i in (11, 22, 33, 44)),
        cv_cells=tuple(protocol.Cell(True, i) for i in (55, 66)),
        out_cells=out,
    )


class SchemaTests(unittest.TestCase):
    def request(self):
        return ServiceRequired(
            ServiceKey(0x1234, 7, 9, 1), bytes(range(64)), bytes(range(32)),
            0x100000000, 64, 3,
        )

    def test_schema_round_trips_exactly(self):
        request = self.request()
        self.assertEqual(ServiceRequired.decode(request.encode()), request)
        response = ServiceResponse(request.key, ServiceStatus.OK, bytes(range(32)))
        self.assertEqual(ServiceResponse.decode(response.encode()), response)

    def test_malformed_fields_are_semantic_failures(self):
        request = self.request()
        mutations = [
            request.encode()[:-1],
            bytes((2,)) + request.encode()[1:],
            request.encode()[:18] + b"\x01" + request.encode()[19:],
        ]
        for payload in mutations:
            with self.subTest(length=len(payload)):
                with self.assertRaises(ServiceSemanticError):
                    ServiceRequired.decode(payload)
        response = bytearray(ServiceResponse(
            request.key, ServiceStatus.OK, bytes(32),
        ).encode())
        for offset, value in ((0, 2), (18, 99), (19, 31)):
            malformed = bytearray(response)
            malformed[offset] = value
            with self.assertRaises(ServiceSemanticError):
                ServiceResponse.decode(bytes(malformed))

    def test_metadata_is_rejected_before_compression(self):
        key = ServiceKey(1, 1, 1, 1)
        for counter, block_len, flags in (
            (-1, 64, 0),
            (1 << 64, 64, 0),
            (0, 65, 0),
            (0, 64, 0x80),
        ):
            with self.assertRaises(ServiceSemanticError):
                ServiceRequired(
                    key, bytes(64), bytes(32), counter, block_len, flags,
                )

    def test_keys_and_direct_responses_enforce_schema_ranges(self):
        for key in (
            (0, 1, 1, 1),
            (1 << 64, 1, 1, 1),
            (1, -1, 1, 1),
            (1, 1 << 32, 1, 1),
            (1, 1, -1, 1),
            (1, 1, 1 << 32, 1),
            (1, 1, 1, 1 << 8),
        ):
            with self.subTest(key=key):
                with self.assertRaises(ServiceSemanticError):
                    ServiceKey(*key)
        key = ServiceKey(1, 1, 1, 1)
        with self.assertRaises(ServiceSemanticError):
            ServiceResponse(key, ServiceStatus.OK, b"short")


class ScatterGatherDesignContractTests(unittest.TestCase):
    def test_authored_rtl_exposes_external_only_payload_contract(self):
        tx = (ROOT / "asic_core" / "rtl" / "lsc1_packet_tx.sv").read_text()
        design = (ROOT / "docs" / "BLAKE3_EXTERNAL_SERVICE.md").read_text()
        self.assertNotIn("[159:0]", tx)
        self.assertNotIn("saved_payload", tx)
        self.assertNotIn("saved_external", tx)
        self.assertNotRegex(tx, r"input\s+wire\s+payload_external(?:\s|,)")
        self.assertIn("payload_external_data", tx)
        self.assertIn("payload_index", tx)
        self.assertIn("payload_external_valid", tx)
        self.assertIn("immutable while", tx)
        frontend = (ROOT / "asic_core" / "rtl" / "lsc1_packet_frontend.sv").read_text()
        mux = (ROOT / "asic_core" / "rtl" / "lsc1_response_payload_mux.sv").read_text()
        self.assertIn("else if (kind == 3) begin", mux)
        self.assertIn("scalar_staged_write_value", frontend)
        self.assertIn("scatter/gather", design)
        self.assertIn("Authored RTL service boundary", design)


class OfficialDifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            ["cargo", "build", "--locked", "--manifest-path", str(MANIFEST)],
            cwd=ROOT, text=True, capture_output=True,
        )
        if result.returncode:
            raise ServiceInfrastructureError(
                "official BLAKE3 oracle build failed:\n" + result.stderr
            )

    def official(self, request):
        result = subprocess.run(
            [str(BINARY)], input=(
                f"{request.message.hex()} {request.chaining_value.hex()} "
                f"{request.counter} {request.block_len} {request.flags}\n"
            ), text=True, capture_output=True,
        )
        if result.returncode:
            raise ServiceInfrastructureError(
                "official BLAKE3 oracle execution failed:\n" + result.stderr
            )
        try:
            return bytes.fromhex(result.stdout.strip())
        except ValueError as exc:
            raise ServiceInfrastructureError("official oracle returned non-hex") from exc

    def test_host_compression_matches_official_low_level_library(self):
        rng = random.Random(SEED)
        block_lengths = (0, 1, 31, 32, 63, 64)
        counters = (0, 1, 2**32 - 1, 2**32, 2**64 - 1)
        flags = (0, 1, 2, 3, 4, 8, 16, 32, 64, 11)
        vectors = [
            (bytes(64), bytes(32), 0, 0, 0),
            (bytes([0xFF]) * 64, bytes([0xFF]) * 32, 2**64 - 1, 64, 3),
            (bytes(range(64)), bytes(range(32)), 2**32, 63, 11),
        ]
        vectors.extend(
            (rng.randbytes(64), rng.randbytes(32), rng.choice(counters),
             rng.choice(block_lengths), rng.choice(flags))
            for _ in range(64)
        )
        for message, cv, counter, block_len, flag in vectors:
            request = ServiceRequired(
                ServiceKey(1, 1, 1, 1), message, cv, counter, block_len, flag,
            )
            self.assertEqual(compress(request), self.official(request))


class AdapterAndModelTests(unittest.TestCase):
    def pending(self, *, rx_gaps=None, tx_gaps=None, out=None):
        endpoint = protocol.Lsc1Endpoint()
        frame = blake3_request(out=out or (protocol.ABSENT, protocol.ABSENT))
        reply = exchange(endpoint, frame, rx_gaps=rx_gaps, tx_gaps=tx_gaps)
        self.assertIs(reply.status, protocol.Status.SERVICE_REQUIRED)
        adapter = ModelServiceAdapter(0xAABBCCDD)
        request = adapter.accept_required(reply.payload)
        return endpoint, adapter, request

    def test_stalls_do_not_change_service_or_result(self):
        baseline = self.pending()
        stalled = self.pending(
            rx_gaps=[0, 1, 0, 2] * 50, tx_gaps=[2, 0, 1] * 50,
        )
        self.assertEqual(baseline[2], stalled[2])
        for endpoint, adapter, request in (baseline, stalled):
            response = adapter.compute(request)
            reply = exchange(
                endpoint, adapter.to_v1(response),
                rx_gaps=[1, 0] * 30, tx_gaps=[0, 2] * 100,
            )
            self.assertIs(reply.status, protocol.Status.OK)
            self.assertFalse(endpoint.state_valid)
            retired = exchange(endpoint, protocol.build_retire(
                txn_id=1, result_crc=protocol.crc32(reply.payload),
            ))
            self.assertIs(retired.status, protocol.Status.RETIRED)
            adapter.complete(request.key)

    def test_wrong_binding_stale_epoch_abort_and_reset_are_rejected(self):
        endpoint, adapter, request = self.pending()
        good = adapter.compute(request)
        for key in (
            ServiceKey(request.key.session_epoch + 1, 1, 1, 1),
            ServiceKey(request.key.session_epoch, 2, 1, 1),
            ServiceKey(request.key.session_epoch, 1, 2, 1),
            ServiceKey(request.key.session_epoch, 1, 1, 2),
        ):
            with self.assertRaises(ServiceSemanticError):
                adapter.to_v1(ServiceResponse(key, ServiceStatus.OK, good.digest))
        adapter.abort()
        with self.assertRaises(ServiceSemanticError):
            adapter.to_v1(good)
        endpoint.step(abort=True)
        self.assertIsNone(endpoint.staged)
        adapter.reset(0xAABBCCDE)
        with self.assertRaises(ServiceSemanticError):
            adapter.to_v1(good)

    def test_retry_requires_identical_operands_and_abort_tombstones_key(self):
        _, adapter, request = self.pending()
        endpoint = protocol.Lsc1Endpoint()
        reply = exchange(endpoint, blake3_request())
        altered = bytearray(reply.payload)
        altered[10] ^= 1
        with self.assertRaises(ServiceSemanticError):
            adapter.accept_required(bytes(altered))
        self.assertEqual(adapter.accept_required(reply.payload), request)
        adapter.abort()
        with self.assertRaises(ServiceSemanticError):
            adapter.accept_required(reply.payload)

    def test_compute_requires_the_exact_accepted_request(self):
        _, adapter, request = self.pending()
        altered = ServiceRequired(
            request.key,
            bytes((request.message[0] ^ 1,)) + request.message[1:],
            request.chaining_value,
            request.counter,
            request.block_len,
            request.flags,
        )
        with self.assertRaises(ServiceSemanticError):
            adapter.compute(altered)
        self.assertEqual(adapter.compute(request).key, request.key)

    def test_reset_rejects_invalid_epoch_without_changing_state(self):
        _, adapter, request = self.pending()
        for epoch in (0, -1, 1 << 64):
            with self.subTest(epoch=epoch):
                with self.assertRaises(ValueError):
                    adapter.reset(epoch)
                self.assertEqual(adapter.session_epoch, request.key.session_epoch)
                self.assertEqual(adapter.outstanding, request.key)

    def test_reset_never_reuses_an_earlier_epoch(self):
        adapter = ModelServiceAdapter(0xA)
        adapter.reset(0xB)
        with self.assertRaises(ValueError):
            adapter.reset(0xA)
        self.assertEqual(adapter.session_epoch, 0xB)
        adapter.reset(0xC)
        with self.assertRaises(ValueError):
            adapter.reset(0xB)
        self.assertEqual(adapter.session_epoch, 0xC)

    def test_infrastructure_retry_is_bounded_and_semantic_failure_is_not_retried(self):
        _, adapter, request = self.pending()
        calls = 0
        def flaky(_request):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ServiceInfrastructureError("temporary")
            return bytes(32)
        self.assertEqual(adapter.compute(request, flaky).digest, bytes(32))
        self.assertEqual(calls, 3)

        calls = 0
        def wrong(_request):
            nonlocal calls
            calls += 1
            return b"wrong"
        with self.assertRaises(ServiceSemanticError):
            adapter.compute(request, wrong)
        self.assertEqual(calls, 1)

    def test_wrong_digest_conflict_discards_but_commit_is_atomic(self):
        endpoint, adapter, request = self.pending(
            out=(protocol.Cell(True, 1), protocol.ABSENT),
        )
        bad = ServiceResponse(request.key, ServiceStatus.OK, bytes(32))
        reply = exchange(endpoint, adapter.to_v1(bad))
        self.assertIs(reply.status, protocol.Status.WRITE_CONFLICT)
        self.assertIsNone(endpoint.staged)
        self.assertFalse(endpoint.state_valid)

    def test_duplicate_response_is_stale_after_result_acceptance(self):
        endpoint, adapter, request = self.pending()
        response = adapter.compute(request)
        first = exchange(endpoint, adapter.to_v1(response))
        self.assertIs(first.status, protocol.Status.OK)
        duplicate = exchange(endpoint, adapter.to_v1(response))
        self.assertIs(duplicate.status, protocol.Status.BAD_STATE)
