# Use cases

The primary use is a Mac compiling a leanVM-b program, preparing one complete
scalar instruction transaction, and asking LSC-1 to validate/execute it.  The
Mac persists memory and proof material; LSC-1 returns a compact verified
transition.  An ULX3S may observe and replay these exact byte handshakes for
bring-up.  Neither use case gives the ASIC or FPGA ownership of program memory,
SDRAM, BLAKE3, or proof services.
