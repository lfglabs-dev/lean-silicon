"""Cross-checks `docs/LSC1_TRANSACTION_PROTOCOL.md` against the executable model.

Every size, code and cycle count published in the normative document is derived
from `sim/lsc1_transaction.py`.  These tests re-derive each published table and
fail if the document and the model have drifted apart, so the document's numbers
can never be hand-edited into agreement.

Response payload sizes are not read out of the model's constants but *measured*
by driving real frames through an endpoint, so the document describes bytes the
model actually emits.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import lsc1_transaction as lsc1
from lsc1_transaction import (
    ABSENT,
    CELL_BYTES,
    CRC_BYTES,
    DEFERRED_BYTES,
    DEVICE_ID,
    INDEX_BITS,
    MAX_PAYLOAD_BYTES,
    PROTOCOL_VERSION,
    REQUEST_HEADER_BYTES,
    REQUEST_PAYLOAD_BYTES,
    RESPONSE_HEADER_BYTES,
    SOF_REQUEST,
    SOF_RESPONSE,
    TRANSACTION_PREAMBLE_BYTES,
    WRITE_BYTES,
    Cell,
    Lsc1Endpoint,
    Opcode,
    Profile,
    Status,
)

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs" / "LSC1_TRANSACTION_PROTOCOL.md"
FROZEN_COMMIT = "c308034ab78619b39a59d26f3dc60e7df5b52649"

TEXT = DOCUMENT.read_text(encoding="utf-8")
LINES = TEXT.splitlines()


# --- Markdown parsing. ------------------------------------------------------


def cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def tables() -> list[tuple[str, list[str], list[list[str]]]]:
    """Every pipe table, tagged with the heading it appears under."""
    found: list[tuple[str, list[str], list[list[str]]]] = []
    heading = ""
    index = 0
    while index < len(LINES):
        line = LINES[index]
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        is_header = line.startswith("|") and index + 1 < len(LINES)
        if is_header and set(LINES[index + 1].replace("|", "").strip()) <= {"-", " "}:
            header = cells(line)
            rows = []
            index += 2
            while index < len(LINES) and LINES[index].startswith("|"):
                rows.append(cells(LINES[index]))
                index += 1
            found.append((heading, header, rows))
            continue
        index += 1
    return found


TABLES = tables()


def table_under(prefix: str) -> list[list[str]]:
    """The single table under the heading starting with ``prefix``."""
    matches = [rows for heading, _, rows in TABLES if heading.startswith(prefix)]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one table under {prefix!r}, got {len(matches)}")
    return matches[0]


def tick(value: str) -> str:
    return value.strip().strip("`")


def num(value: str, base: int = 10) -> int:
    return int(tick(value), base)


def headings() -> list[str]:
    return [line.lstrip("#").strip() for line in LINES if line.startswith("#")]


FIELD_WIDTHS = {
    "u8": 1,
    "u16le": 2,
    "u32le": 4,
    "f128le": 16,
    "cell": CELL_BYTES,
    "preamble": TRANSACTION_PREAMBLE_BYTES,
}


def table_total(prefix: str) -> int:
    """Walk an offset table, asserting each row starts where the last ended."""
    rows = table_under(prefix)
    offset = num(rows[0][0])
    for row in rows:
        if num(row[0]) != offset:
            raise AssertionError(f"{prefix}: {row[2]} is at {row[0]}, expected {offset}")
        kind, _, count = row[1].partition("×")
        offset += FIELD_WIDTHS[tick(kind)] * (int(count) if count else 1)
    return offset


def declared_size(heading_prefix: str) -> int:
    """The ``— N bytes`` suffix of a section heading."""
    for heading in headings():
        if heading.startswith(heading_prefix):
            match = re.search(r"—\s*(\d+)\s*bytes\s*$", heading)
            if match is None:
                raise AssertionError(f"heading {heading!r} declares no byte count")
            return int(match.group(1))
    raise AssertionError(f"no heading starting {heading_prefix!r}")


# --- Measured exchanges. ----------------------------------------------------


def measure(endpoint: Lsc1Endpoint, frame: lsc1.RequestFrame) -> lsc1.ResponseFrame:
    response, _ = lsc1.drive(endpoint, frame.encode())
    return lsc1.decode_response(response)


def blake3_frame(txn_id: int = 7) -> lsc1.RequestFrame:
    return lsc1.build_blake3(
        txn_id=txn_id,
        pc=0,
        fp=64,
        profile=Profile.INTERPRETER_COMPAT,
        message_offsets=(1, 2, 3, 4),
        cv_offset=5,
        out_offset=10,
        metadata=0x40,
        message_cells=(Cell(True, 1), Cell(True, 2), Cell(True, 3), Cell(True, 4)),
        cv_cells=(Cell(True, 5), Cell(True, 6)),
        out_cells=(ABSENT, ABSENT),
    )


def blake3_request(endpoint: Lsc1Endpoint) -> lsc1.ResponseFrame:
    return measure(endpoint, blake3_frame())


class DocumentSizeTests(unittest.TestCase):
    def test_frame_size_table_matches_the_codec(self) -> None:
        rows = table_under("5.5")
        published = {tick(row[0]): (num(row[1], 16), num(row[2]), num(row[3])) for row in rows}
        expected = {
            opcode.name: (
                int(opcode),
                REQUEST_PAYLOAD_BYTES[opcode],
                lsc1.request_frame_bytes(opcode),
            )
            for opcode in Opcode
        }
        self.assertEqual(published, expected)

    def test_every_request_schema_heading_declares_its_payload_size(self) -> None:
        for opcode in Opcode:
            if opcode in (Opcode.DEREF_PC, Opcode.DEREF_FP):
                continue  # documented jointly with DEREF_CELL under 7.4
            heading = next(
                head
                for head in headings()
                if head.startswith("7.") and f"`{opcode.name}`" in head
            )
            match = re.search(r"—\s*(\d+)\s*bytes\s*$", heading)
            assert match is not None, heading
            self.assertEqual(
                int(match.group(1)),
                REQUEST_PAYLOAD_BYTES[opcode],
                f"{opcode.name} heading size",
            )

    def test_deref_modes_share_one_schema_and_one_size(self) -> None:
        heading = next(head for head in headings() if head.startswith("7.4"))
        for opcode in (Opcode.DEREF_CELL, Opcode.DEREF_PC, Opcode.DEREF_FP):
            self.assertIn(f"`{opcode.name}`", heading)
            self.assertEqual(REQUEST_PAYLOAD_BYTES[opcode], declared_size("7.4"))

    def test_primitive_type_table_matches_the_codec_widths(self) -> None:
        published = {tick(row[0]): num(row[1]) for row in table_under("6. Primitive")}
        self.assertEqual(
            published,
            {"u8": 1, "u16le": 2, "u32le": 4, "f128le": 16, "cell": CELL_BYTES},
        )

    def test_preamble_table_covers_exactly_the_preamble_bytes(self) -> None:
        self.assertEqual(table_total("6.1"), TRANSACTION_PREAMBLE_BYTES)

    def test_mul_native_schema_extends_the_xor_schema(self) -> None:
        first = table_under("7.2")[0]
        self.assertEqual(num(first[0]), REQUEST_PAYLOAD_BYTES[Opcode.XOR])

    def test_every_offset_table_is_cumulative_and_totals_its_declared_size(self) -> None:
        """Offsets are not taken on trust: each row must start where the last ended."""
        checked = 0
        for heading, header, rows in TABLES:
            if header[:1] != ["Offset"] or any(row[0] == "…" for row in rows):
                continue
            section = heading.split(" ", 1)[0]
            total = table_total(section)
            if any(head.startswith(section) and "bytes" in head for head in headings()):
                self.assertEqual(total, declared_size(section), f"{heading}: total")
            checked += 1
        self.assertGreaterEqual(checked, 12)

    def test_envelope_prose_matches_the_header_constants(self) -> None:
        self.assertIn(f"Request header: **{REQUEST_HEADER_BYTES} bytes**", TEXT)
        self.assertIn(f"Response header: **{RESPONSE_HEADER_BYTES} bytes**", TEXT)
        self.assertIn(
            f"Envelope overhead: **{REQUEST_HEADER_BYTES + CRC_BYTES} bytes** "
            f"({REQUEST_HEADER_BYTES} header + {CRC_BYTES} CRC)",
            TEXT,
        )
        self.assertIn(
            f"Envelope overhead: **{RESPONSE_HEADER_BYTES + CRC_BYTES} bytes**", TEXT
        )
        self.assertIn(f"`MAX_PAYLOAD_BYTES = {MAX_PAYLOAD_BYTES}`", TEXT)
        self.assertIn(f"sof      := 0x{SOF_REQUEST:02X}", TEXT)
        self.assertIn(f"sof      := 0x{SOF_RESPONSE:02X}", TEXT)
        self.assertIn(f"polynomial `0x{lsc1.CRC32_POLYNOMIAL:08X}`", TEXT)

    def test_inline_prose_byte_counts_match_the_driven_endpoint(self) -> None:
        """Sizes stated in words drift as easily as sizes stated in tables."""
        service = blake3_request(Lsc1Endpoint())
        service_required = lsc1.response_frame_bytes(len(service.payload))
        service_response = lsc1.request_frame_bytes(Opcode.SERVICE_RESPONSE)
        fault, _ = lsc1.drive(
            Lsc1Endpoint(), lsc1.build_retire(txn_id=1, result_crc=0).encode()
        )
        flowed = " ".join(TEXT.split())
        for claim in (
            f"same {TRANSACTION_PREAMBLE_BYTES}-byte preamble",
            f"Every fault response is {len(fault)} bytes on the wire.",
            f"{len(service.payload)}-byte payload",
            f"`BLAKE3_REQUEST`'s {service_required + service_response} service bytes",
            f"the {service_required}-byte `SERVICE_REQUIRED` response plus the "
            f"{service_response}-byte `SERVICE_RESPONSE` request",
            f"`INDEX_BITS = {INDEX_BITS}`",
        ):
            self.assertIn(claim, flowed)

    def test_declared_envelope_overhead_is_what_the_codec_adds(self) -> None:
        for opcode in Opcode:
            self.assertEqual(
                lsc1.request_frame_bytes(opcode) - REQUEST_PAYLOAD_BYTES[opcode],
                REQUEST_HEADER_BYTES + CRC_BYTES,
            )
        self.assertEqual(
            lsc1.response_frame_bytes(0), RESPONSE_HEADER_BYTES + CRC_BYTES
        )

    def test_result_payload_row_widths_match_the_encoder(self) -> None:
        rows = table_under("8.1")
        text = " ".join(" ".join(row) for row in rows)
        self.assertIn(f"({WRITE_BYTES} bytes)", text)
        self.assertIn(f"({DEFERRED_BYTES} bytes)", text)

    def test_response_schema_headings_match_measured_payloads(self) -> None:
        endpoint = Lsc1Endpoint()
        negotiate = measure(endpoint, lsc1.build_negotiate(profile=Profile.INTERPRETER_COMPAT))
        self.assertIs(negotiate.status, Status.OK)
        self.assertEqual(len(negotiate.payload), declared_size("8.4"))

        service = blake3_request(endpoint)
        self.assertIs(service.status, Status.SERVICE_REQUIRED)
        self.assertEqual(len(service.payload), declared_size("8.2"))

        status = measure(endpoint, lsc1.build_status_query())
        self.assertIs(status.status, Status.INFO)
        self.assertEqual(len(status.payload), declared_size("8.5"))

        fault = measure(endpoint, lsc1.build_retire(txn_id=999, result_crc=0))
        self.assertGreaterEqual(int(fault.status), 0x80)
        self.assertEqual(len(fault.payload), declared_size("8.6"))

        endpoint = Lsc1Endpoint()
        response, _ = lsc1.drive(endpoint, _staged_xor().encode())
        staged = endpoint.staged
        assert staged is not None
        retired = measure(
            endpoint,
            lsc1.build_retire(txn_id=staged.txn_id, result_crc=staged.result_crc),
        )
        self.assertIs(retired.status, Status.RETIRED)
        self.assertEqual(len(retired.payload), declared_size("8.3"))

    def test_negotiate_reply_schema_constants_are_the_model_constants(self) -> None:
        text = " ".join(" ".join(row) for row in table_under("8.4"))
        self.assertIn(f"(`{PROTOCOL_VERSION}`)", text)
        self.assertIn(f"(`{MAX_PAYLOAD_BYTES}`)", text)
        self.assertIn(f"(`{INDEX_BITS}`)", text)
        self.assertIn(f"`0x{DEVICE_ID:X}`", text)


def _staged_xor() -> lsc1.RequestFrame:
    return lsc1.build_binary_op(
        Opcode.XOR,
        txn_id=1,
        pc=0,
        fp=64,
        profile=Profile.INTERPRETER_COMPAT,
        offsets=(1, 2, 3),
        cells=(Cell(True, 0xDEAD), Cell(True, 0xBEEF), ABSENT),
    )


def any_frame(opcode: Opcode) -> lsc1.RequestFrame:
    """A well-formed frame per opcode, sound but for the state it is sent in."""
    preamble = dict(txn_id=1, pc=0, fp=64, profile=Profile.INTERPRETER_COMPAT)
    present = Cell(True, 0xABC)
    if opcode in (Opcode.XOR, Opcode.MUL_NATIVE):
        return lsc1.build_binary_op(
            opcode, **preamble, offsets=(1, 2, 3), cells=(present, present, ABSENT)
        )
    if opcode is Opcode.SET_CONSTANT:
        return lsc1.build_set_constant(**preamble, offset=1, constant=9, cell=ABSENT)
    if opcode in (Opcode.DEREF_CELL, Opcode.DEREF_PC, Opcode.DEREF_FP):
        return lsc1.build_deref(
            opcode,
            **preamble,
            alpha=1,
            beta=2,
            gamma=3,
            pointer=Cell(True, lsc1.field_encode(8)),
            base=8,
            target=ABSENT,
            local=present,
        )
    if opcode is Opcode.JUMP:
        return lsc1.build_jump(
            **preamble,
            offsets=(1, 2, 3),
            cells=(Cell(True, 0), Cell(True, 1), Cell(True, 1)),
            taken=False,
            dest_pc=0,
            dest_fp=0,
            proposed_inverse=ABSENT,
        )
    if opcode is Opcode.BLAKE3_REQUEST:
        return blake3_frame(txn_id=1)
    if opcode is Opcode.NEGOTIATE:
        return lsc1.build_negotiate(profile=Profile.INTERPRETER_COMPAT)
    if opcode is Opcode.SERVICE_RESPONSE:
        return lsc1.build_service_response(txn_id=1, service_id=1, digest=(1, 2))
    if opcode is Opcode.RETIRE:
        return lsc1.build_retire(txn_id=1, result_crc=0)
    return lsc1.build_status_query()


def endpoint_in(state: str) -> Lsc1Endpoint:
    endpoint = Lsc1Endpoint()
    if state == "RESULT_PENDING":
        measure(endpoint, _staged_xor())
    elif state == "SERVICE_PENDING":
        measure(endpoint, blake3_frame(txn_id=1))
    return endpoint


class DocumentStateMachineTests(unittest.TestCase):
    def test_state_table_legal_opcodes_are_exactly_those_not_refused(self) -> None:
        published = {
            tick(row[0]): {tick(name) for name in row[1].split(",")}
            for row in table_under("10. Transaction")
        }
        for state, listed in published.items():
            accepted = set()
            for opcode in Opcode:
                reply = measure(endpoint_in(state), any_frame(opcode))
                if reply.status is not Status.BAD_STATE:
                    accepted.add(opcode.name)
            expected = set(listed)
            if "instruction opcodes" in expected:
                expected.discard("instruction opcodes")
                expected |= {op.name for op in lsc1.INSTRUCTION_OPCODES}
            self.assertEqual(accepted, expected, f"legal opcodes in {state}")

    def test_a_transaction_retires_at_most_once(self) -> None:
        endpoint = Lsc1Endpoint()
        measure(endpoint, _staged_xor())
        staged = endpoint.staged
        assert staged is not None
        first = measure(
            endpoint,
            lsc1.build_retire(txn_id=staged.txn_id, result_crc=staged.result_crc),
        )
        self.assertIs(first.status, Status.RETIRED)
        second = measure(
            endpoint,
            lsc1.build_retire(txn_id=staged.txn_id, result_crc=staged.result_crc),
        )
        self.assertIs(second.status, Status.BAD_STATE)

    def test_no_fault_moves_committed_pc_fp_or_retire_seq(self) -> None:
        """The §9.1 claim, read at the §8.5 offsets the document publishes."""
        rows = table_under("8.5")

        def offset_of(description: str) -> int:
            return next(num(row[0]) for row in rows if description in row[2])

        committed = tuple(
            offset_of(name)
            for name in ("retire_seq", "committed `pc`", "committed `fp`", "state valid")
        )

        def snapshot(endpoint: Lsc1Endpoint) -> tuple[int, ...]:
            payload = measure(endpoint, lsc1.build_status_query()).payload
            return tuple(
                int.from_bytes(payload[at : at + 4], "little") for at in committed
            )

        endpoint = Lsc1Endpoint()
        before = snapshot(endpoint)
        for opcode in (Opcode.RETIRE, Opcode.SERVICE_RESPONSE):
            self.assertIs(measure(endpoint, any_frame(opcode)).status, Status.BAD_STATE)
        self.assertEqual(snapshot(endpoint), before)

        measure(endpoint, _staged_xor())
        staged = endpoint.staged
        assert staged is not None
        mismatch = measure(
            endpoint, lsc1.build_retire(txn_id=staged.txn_id, result_crc=~staged.result_crc & 0xFFFFFFFF)
        )
        self.assertIs(mismatch.status, Status.RETIRE_MISMATCH)
        self.assertEqual(snapshot(endpoint), before)


class DocumentCodeTests(unittest.TestCase):
    def test_status_table_is_exactly_the_status_enum(self) -> None:
        published = {tick(row[0]): num(row[1], 16) for row in table_under("9. Status")}
        self.assertEqual(published, {status.name: int(status) for status in Status})

    def test_profile_table_is_exactly_the_profile_enum(self) -> None:
        published = {tick(row[0]): num(row[1], 16) for row in table_under("12. Profiles")}
        self.assertEqual(published, {profile.name: int(profile) for profile in Profile})

    def test_state_table_names_exactly_the_model_states(self) -> None:
        published = {tick(row[0]) for row in table_under("10. Transaction")}
        self.assertEqual(published, {state.name for state in lsc1.TxnState})

    def test_fault_codes_are_all_at_or_above_the_fault_bit(self) -> None:
        for row in table_under("9. Status"):
            code = num(row[1], 16)
            expected_fault = code >= 0x80
            self.assertEqual(
                Status(code).name == tick(row[0]),
                True,
                f"{row[0]} is not code 0x{code:02X}",
            )
            self.assertEqual(expected_fault, code not in (0x00, 0x01, 0x02, 0x03))


class DocumentBudgetTests(unittest.TestCase):
    def test_assumption_table_is_the_model_assumptions(self) -> None:
        published = {tick(row[0]): num(row[1]) for row in table_under("13.1")}
        assumptions = lsc1.ASSUMPTIONS
        self.assertEqual(
            published,
            {
                "beat": assumptions.beat,
                "field_mul": assumptions.field_mul,
                "field_xor": assumptions.field_xor,
                "xtime": assumptions.xtime,
                "compare": assumptions.compare,
                "decode": assumptions.decode,
            },
        )

    def test_encode_index_cost_is_stated_as_the_model_computes_it(self) -> None:
        cost = lsc1.ASSUMPTIONS.encode_index()
        self.assertIn(f"`{INDEX_BITS} * (field_mul + xtime) = {cost}`", TEXT)
        for mention in re.findall(r"(\d+)-cycle operation|is `(\d+)` cycles", TEXT):
            stated = next(value for value in mention if value)
            self.assertEqual(int(stated), cost)

    def test_fermat_inverse_cost_is_the_square_and_multiply_count(self) -> None:
        field_bits = lsc1.MASK128.bit_length()
        exponent = lsc1.MASK128 - 1
        squarings = exponent.bit_length() - 1
        multiplies = bin(exponent).count("1") - 1
        self.assertIn(
            f"`x**(2**{field_bits} - 2)` costs"
            f" {squarings} squarings and {multiplies} multiplies",
            TEXT,
        )

    def test_per_opcode_budget_tables_match_the_model(self) -> None:
        for prefix, profile in (("13.2", Profile.INTERPRETER_COMPAT), ("13.3", Profile.FORWARD_ONLY)):
            with self.subTest(profile=profile.name):
                self.assertIn(f"`{profile.name}`", next(
                    head for head in headings() if head.startswith(prefix)
                ))
                published = {
                    tick(row[0]): tuple(num(value) for value in row[1:])
                    for row in table_under(prefix)
                }
                expected = {
                    entry.opcode.name: (
                        entry.request_bytes,
                        entry.result_bytes,
                        entry.service_bytes,
                        entry.execute_cycles,
                        entry.round_trip_cycles,
                    )
                    for entry in lsc1.budget_table(profile)
                }
                self.assertEqual(published, expected)

    def test_control_frame_table_matches_driven_exchanges(self) -> None:
        rows = {tick(row[0]): (row[1], row[2]) for row in table_under("13.4")}
        endpoint = Lsc1Endpoint()

        negotiate, _ = lsc1.drive(endpoint, lsc1.build_negotiate(profile=Profile.INTERPRETER_COMPAT).encode())
        self.assertEqual(
            rows["NEGOTIATE"],
            (str(lsc1.request_frame_bytes(Opcode.NEGOTIATE)), str(len(negotiate))),
        )

        status, _ = lsc1.drive(endpoint, lsc1.build_status_query().encode())
        self.assertEqual(
            rows["STATUS_QUERY"],
            (str(lsc1.request_frame_bytes(Opcode.STATUS_QUERY)), str(len(status))),
        )

        lsc1.drive(endpoint, _staged_xor().encode())
        staged = endpoint.staged
        assert staged is not None
        retired, _ = lsc1.drive(
            endpoint,
            lsc1.build_retire(txn_id=staged.txn_id, result_crc=staged.result_crc).encode(),
        )
        self.assertEqual(
            rows["RETIRE"],
            (str(lsc1.request_frame_bytes(Opcode.RETIRE)), str(len(retired))),
        )

        self.assertEqual(
            rows["SERVICE_RESPONSE"][0],
            str(lsc1.request_frame_bytes(Opcode.SERVICE_RESPONSE)),
        )

        fault, _ = lsc1.drive(Lsc1Endpoint(), lsc1.build_retire(txn_id=1, result_crc=0).encode())
        self.assertEqual(rows["any fault"][1], str(len(fault)))


class DocumentProvenanceTests(unittest.TestCase):
    def test_every_upstream_citation_is_pinned_to_the_frozen_commit(self) -> None:
        urls = re.findall(r"https://github\.com/leanEthereum/leanVM-b/[^\s)]+", TEXT)
        self.assertGreater(len(urls), 0)
        for url in urls:
            self.assertIn(FROZEN_COMMIT, url, url)

    def test_no_upstream_citation_points_at_a_moving_branch(self) -> None:
        for moving in ("/blob/main/", "/tree/main/", "/blob/master/", "/blob/HEAD/"):
            self.assertNotIn(moving, TEXT)

    def test_document_claims_no_verification_fabrication_validation_or_readiness(self) -> None:
        lowered = TEXT.lower()
        for forbidden in ("tiny tapeout ready", "tapeout-ready", "formally verified", "fpga validated"):
            self.assertNotIn(forbidden, lowered)

    def test_document_does_not_reference_the_retired_module_name(self) -> None:
        self.assertNotIn("tt_um_leanvm_b_mincore", TEXT)

    def test_document_names_the_module_and_test_that_generate_its_tables(self) -> None:
        self.assertIn("sim/lsc1_transaction.py", TEXT)
        self.assertIn(Path(__file__).name.replace(".py", ""), TEXT)

    def test_document_version_matches_the_protocol_version(self) -> None:
        self.assertTrue(LINES[0].startswith(f"# LSC-1 Transaction Protocol, version {PROTOCOL_VERSION}"))

    def test_every_internal_link_resolves_to_a_heading(self) -> None:
        def slug(heading: str) -> str:
            # GitHub's rule: drop punctuation, then map each space to a hyphen.
            return re.sub(r"[^\w\s-]", "", heading.lower()).replace(" ", "-")

        anchors = {slug(heading) for heading in headings()}
        for link in re.findall(r"\]\(#([^)]+)\)", TEXT):
            self.assertIn(link, anchors)

    def test_contents_list_links_to_every_top_level_section(self) -> None:
        top_level = [head for head in headings() if re.match(r"^\d+\. ", head)]
        for heading in top_level:
            number = heading.split(".", 1)[0]
            self.assertRegex(TEXT, rf"\n{number}\. \[[^\]]+\]\(#", f"missing contents entry for {heading}")


def result_writes(reply: lsc1.ResponseFrame) -> dict[int, int]:
    count = reply.payload[12]
    body = reply.payload[13 : 13 + count * WRITE_BYTES]
    return {
        int.from_bytes(body[at : at + 4], "little"): int.from_bytes(
            body[at + 4 : at + 20], "little"
        )
        for at in range(0, len(body), WRITE_BYTES)
    }


def result_deferred(reply: lsc1.ResponseFrame) -> int:
    at = 13 + reply.payload[12] * WRITE_BYTES
    return reply.payload[at]


class DocumentSemanticsTests(unittest.TestCase):
    """The §12 profile tables are the frozen-source disagreement.

    They are checked by driving each documented situation through the endpoint
    and classifying what it actually did, so neither column can be edited into
    describing behaviour the model does not have.
    """

    FP = 64

    def _negotiated(self, profile: Profile) -> Lsc1Endpoint:
        endpoint = lsc1.Lsc1OracleEndpoint()
        reply = measure(endpoint, lsc1.build_negotiate(profile=profile))
        self.assertIs(reply.status, Status.OK)
        return endpoint

    def _binary(self, opcode: Opcode, profile: Profile, cells) -> lsc1.ResponseFrame:
        return measure(
            self._negotiated(profile),
            lsc1.build_binary_op(
                opcode,
                txn_id=1,
                pc=0,
                fp=self.FP,
                profile=profile,
                offsets=(1, 2, 3),
                cells=cells,
            ),
        )

    def _binary_outcome(self, opcode: Opcode, profile: Profile, cells) -> str:
        reply = self._binary(opcode, profile, cells)
        if reply.status is not Status.OK:
            return reply.status.name
        left, right, dest = (self.FP + offset for offset in (1, 2, 3))
        writes = result_writes(reply)
        if set(writes) == {left}:
            return "back-solve"
        if set(writes) != {dest}:
            raise AssertionError(f"unexpected writes {writes}")
        return "zero-fill" if not cells[0].present else "forward"

    def test_binary_profile_table_matches_driven_transitions(self) -> None:
        present, other = Cell(True, 0x11), Cell(True, 0x22)
        situations = {
            "both operands present": (present, other, ABSENT),
            "destination written, exactly one operand absent": (
                ABSENT,
                other,
                Cell(True, 0x33),
            ),
            "any operand absent otherwise": (ABSENT, other, ABSENT),
        }
        phrases = {
            "back-solve": "back-solve the absent operand",
            "zero-fill": "absent reads as zero",
            "forward": "forward-compute, write once",
            "UNSUPPORTED_IN_PROFILE": "`UNSUPPORTED_IN_PROFILE`",
        }
        rows = table_under("12.2")
        self.assertEqual({row[0] for row in rows}, set(situations))
        for row in rows:
            compat_text, forward_text = row[1], row[2]
            if forward_text == "same":
                forward_text = compat_text
            for profile, published in (
                (Profile.INTERPRETER_COMPAT, compat_text),
                (Profile.FORWARD_ONLY, forward_text),
            ):
                with self.subTest(situation=row[0], profile=profile.name):
                    outcome = self._binary_outcome(
                        Opcode.XOR, profile, situations[row[0]]
                    )
                    self.assertIn(phrases[outcome], published)

    def _deref_outcome(self, profile: Profile, target: Cell, local: Cell) -> str:
        reply = measure(
            self._negotiated(profile),
            lsc1.build_deref(
                Opcode.DEREF_CELL,
                txn_id=1,
                pc=0,
                fp=self.FP,
                profile=profile,
                alpha=1,
                beta=2,
                gamma=3,
                pointer=Cell(True, lsc1.field_encode(8)),
                base=8,
                target=target,
                local=local,
            ),
        )
        if reply.status is not Status.OK:
            return reply.status.name
        writes = set(result_writes(reply))
        if writes == {8 + 2}:
            return "T := L"
        if writes == {self.FP + 3}:
            return "L := T"
        self.assertEqual(writes, set())
        return "deferred" if result_deferred(reply) else "no write"

    def test_deref_cell_quadrant_table_matches_driven_transitions(self) -> None:
        phrases = {
            "T := L": "write `T := L`",
            "L := T": "write `L := T`",
            "deferred": "deferred equality",
            "no write": "no write",
            "UNSUPPORTED_IN_PROFILE": "`UNSUPPORTED_IN_PROFILE`",
        }
        written = Cell(True, 0x77)
        rows = table_under("12.3")
        self.assertEqual(len(rows), 4)
        for row in rows:
            target = written if row[0] == "yes" else ABSENT
            local = written if row[1] == "yes" else ABSENT
            compat_text, forward_text = row[2], row[3]
            if forward_text == "same":
                forward_text = compat_text
            for profile, published in (
                (Profile.INTERPRETER_COMPAT, compat_text),
                (Profile.FORWARD_ONLY, forward_text),
            ):
                with self.subTest(quadrant=(row[0], row[1]), profile=profile.name):
                    outcome = self._deref_outcome(profile, target, local)
                    self.assertIn(phrases[outcome], published)

    def test_default_profile_after_reset_is_the_one_the_document_names(self) -> None:
        self.assertIn(
            f"default active profile after reset is `{Lsc1Endpoint().profile.name}`",
            TEXT,
        )


if __name__ == "__main__":
    unittest.main()
