# Historical M2 controller

`src/leanvm_b_m2_scalar_controller.sv` is a historical bounded-memory,
wide-port test controller. It is intentionally outside `asic_core/`, is not
the LSC-1 top or packet ABI, and must not be cited as evidence that LSC-1 owns
memory, fetch, pointer resolution, or inversion. Its retained tests preserve
the original experiment's behavior.
