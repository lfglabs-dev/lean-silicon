#!/usr/bin/env python3
"""Require real failures from focused SET/XOR/MUL lifecycle mutations."""

try:
    from formal import check_deref_retire_formal_mutations as checks
except ModuleNotFoundError:
    import check_deref_retire_formal_mutations as checks

checks.SBY_NAME = "scalar_lifecycle.sby"
checks.TEMP_PREFIX = "scalar"
checks.MUTATIONS = [
    ("set_wrong_result_value", "set_accepted_result_safety", "lsc1_packet_frontend.sv",
     "write_value = result_value;", "write_value = 0;"),
    ("xor_wrong_result_value", "xor_accepted_result_safety", "lsc1_packet_frontend.sv",
     "write_value = product;", "write_value = 0;"),
    ("mul_wrong_result_value", "mul_accepted_result_safety", "lsc1_packet_frontend.sv",
     "write_value = product;", "write_value = 0;"),
    ("result_crc_binding", "set_accepted_result_safety", "lsc1_packet_frontend.sv",
     "staged_result_crc <= tx_payload_crc;",
     "staged_result_crc <= tx_payload_crc ^ 32'h00000001;"),
    ("duplicate_retirement", "mul_matching_retire_safety", "lsc1_packet_frontend.sv",
     "retire_seq <= retire_seq + 1'b1;\n                        result_pending <= 1'b0;",
     "retire_seq <= retire_seq + 1'b1;\n                        result_pending <= 1'b1;"),
]

if __name__ == "__main__":
    raise SystemExit(checks.main())
