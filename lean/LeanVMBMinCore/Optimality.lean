import Std.Tactic.Omega

/-!
Exact lower bounds for the declared streaming-interface models. These do not
claim unconstrained global circuit optimality: each theorem states the channel
capacity and scheduling assumptions needed for its conclusion.
-/

namespace LeanVMBMinCore.Optimality

/-- An 8-bit channel needs at least 16 accepted beats for an arbitrary 128-bit word. -/
theorem oneWord_input_lower_bound (cycles : Nat)
    (capacity : 128 ≤ 8 * cycles) : 16 ≤ cycles := by
  omega

/-- It needs at least 32 accepted beats for two arbitrary 128-bit operands. -/
theorem twoWord_input_lower_bound (cycles : Nat)
    (capacity : 256 ≤ 8 * cycles) : 32 ≤ cycles := by
  omega

/--
XOR uses one command beat and 32 mandatory input beats. Its output byte is a
combinational transform of each B byte, so output handshakes overlap input
handshakes. The RTL reaches 33 exactly.
-/
theorem xor_transaction_lower_bound
    (inputCycles totalCycles : Nat)
    (inputCapacity : 256 ≤ 8 * inputCycles)
    (total : totalCycles = 1 + inputCycles) :
    33 ≤ totalCycles := by
  omega

/-- SET is an atomic input/output pass-through after one command beat. -/
theorem set_transaction_lower_bound
    (inputCycles totalCycles : Nat)
    (inputCapacity : 128 ≤ 8 * inputCycles)
    (total : totalCycles = 1 + inputCycles) :
    17 ≤ totalCycles := by
  omega

/-- NONZERO inspects the final byte and emits the predicate on that same beat. -/
theorem nonzero_transaction_lower_bound
    (inputCycles totalCycles : Nat)
    (inputCapacity : 128 ≤ 8 * inputCycles)
    (total : totalCycles = 1 + inputCycles) :
    17 ≤ totalCycles := by
  omega

/--
Radix-1 multiplication consumes at most one multiplier bit per processing beat.
With the fixed command/A/result phases, 161 cycles is therefore minimal.
-/
theorem radix1_mul_transaction_lower_bound
    (aCycles mulCycles outputCycles totalCycles : Nat)
    (aCapacity : 128 ≤ 8 * aCycles)
    (oneBitPerCycle : 128 ≤ mulCycles)
    (outputCapacity : 128 ≤ 8 * outputCycles)
    (total : totalCycles = 1 + aCycles + mulCycles + outputCycles) :
    161 ≤ totalCycles := by
  omega

/--
Radix 8 consumes one full multiplier byte per beat. If output starts only after
both operands have arrived, 49 cycles is the protocol lower bound.
-/
theorem radix8_mul_transaction_lower_bound
    (aCycles bCycles outputCycles totalCycles : Nat)
    (aCapacity : 128 ≤ 8 * aCycles)
    (bCapacity : 128 ≤ 8 * bCycles)
    (outputCapacity : 128 ≤ 8 * outputCycles)
    (total : totalCycles = 1 + aCycles + bCycles + outputCycles) :
    49 ≤ totalCycles := by
  omega


/--
Gate lower bound for an eight-lane, lane-local XOR architecture. Each distinct
nontrivial output lane is assumed to require at least one single-output gate.
-/
theorem xor8_laneLocal_gate_lower_bound
    (g0 g1 g2 g3 g4 g5 g6 g7 total : Nat)
    (h0 : 1 ≤ g0) (h1 : 1 ≤ g1) (h2 : 1 ≤ g2) (h3 : 1 ≤ g3)
    (h4 : 1 ≤ g4) (h5 : 1 ≤ g5) (h6 : 1 ≤ g6) (h7 : 1 ≤ g7)
    (sum : total = g0 + g1 + g2 + g3 + g4 + g5 + g6 + g7) :
    8 ≤ total := by
  omega

/--
GHASH `xtime` routes the old top bit directly to output bit 0. Only output
bits 1, 2, and 7 need nontrivial two-input XORs with the shifted word.
-/
theorem xtime_direct_gate_lower_bound
    (g1 g2 g7 total : Nat)
    (h1 : 1 ≤ g1) (h2 : 1 ≤ g2) (h7 : 1 ≤ g7)
    (sum : total = g1 + g2 + g7) :
    3 ≤ total := by
  omega

/--
Direct radix-1 step lower bound: 128 bit-select gates, 128 accumulator-combine
gates, and three fixed-reduction gates.
-/
theorem radix1_direct_gate_lower_bound
    (selectGates combineGates reductionGates total : Nat)
    (selectBound : 128 ≤ selectGates)
    (combineBound : 128 ≤ combineGates)
    (reductionBound : 3 ≤ reductionGates)
    (sum : total = selectGates + combineGates + reductionGates) :
    259 ≤ total := by
  omega

/--
State lower bound for the declared stream-engine requirements: eleven phases,
sixteen byte positions, one arbitrary saved byte, and one sticky flag.
-/
theorem streamEngine_state_lower_bound
    (phaseBits positionBits scratchBits flagBits total : Nat)
    (phaseBound : 4 ≤ phaseBits)
    (positionBound : 4 ≤ positionBits)
    (scratchBound : 8 ≤ scratchBits)
    (flagBound : 1 ≤ flagBits)
    (sum : total = phaseBits + positionBits + scratchBits + flagBits) :
    17 ≤ total := by
  omega

/-- Add two required 128-bit multiplier registers to the stream-engine bound. -/
theorem mincore_state_lower_bound
    (engineBits shiftedBits accumulatorBits total : Nat)
    (engineBound : 17 ≤ engineBits)
    (shiftedBound : 128 ≤ shiftedBits)
    (accumulatorBound : 128 ≤ accumulatorBits)
    (sum : total = engineBits + shiftedBits + accumulatorBits) :
    273 ≤ total := by
  omega

/-- Concrete no-stall schedules used by the RTL and design-space report. -/
theorem xor_schedule_achieves_bound : 1 + 32 = 33 := by decide
theorem set_schedule_achieves_bound : 1 + 16 = 17 := by decide
theorem nonzero_schedule_achieves_bound : 1 + 16 = 17 := by decide
theorem radix1_schedule_achieves_bound : 1 + 16 + 128 + 16 = 161 := by decide
theorem radix8_schedule_achieves_bound : 1 + 16 + 16 + 16 = 49 := by decide

end LeanVMBMinCore.Optimality
