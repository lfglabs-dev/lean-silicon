import LeanVMBMinCore.RTLRefinement

/-!
# Inductive LSC-1u trace refinement

This module strengthens the retained-boundary result in `RTLRefinement.lean`
from one completed command to arbitrary finite traces.  The transition system
is a Lean mirror of the externally relevant control phases in
`src/lsc1u_core.sv` at repository commit
`f10be11b05a4e798a962e13c61de2eff8cd5ddec`:

* IDLE accepts exactly XOR (`0x01`), MUL (`0x02`), and SET (`0x03`), or stages
  the RTL's `0xe0` invalid-command fault response;
* execution computes the operation result specified by `RTLRefinement.result`;
* TRANSMIT exposes all sixteen least-significant-byte-first response beats,
  holds the current byte stable while `tx_ready = false`, and commits exactly
  once only after the sixteenth accepted transfer;
* reset and `ena = false` abort all in-flight work and return to IDLE.

The model deliberately collapses the byte counters and the 128 internal MUL
bit cycles into the `execute` transition.  Their concrete correspondence is
proved separately by `formal/lsc1u_compositional_refinement.sby` and
`formal/gf128_mul_stream_refinement.sby`.  Consequently the theorem below is
an inductive refinement of the pinned *retained RTL boundary*, not a theorem
obtained by importing SystemVerilog into Lean, not a packet-controller result,
and not RTL-to-netlist equivalence.
-/

namespace LeanVMBMinCore.RTLTraceRefinement

open LeanVMBMinCore.RTLRefinement

abbrev Word := BitVec 128

/-- Retained control phases of the shipped LSC-1u implementation. -/
inductive Phase where
  | idle
  | execute (transaction : AcceptedTransaction)
  | transmit (transaction : AcceptedTransaction) (index : Fin 16)
  | fault
  deriving DecidableEq, Repr

/-- Observable/ghost state used by the trace invariant.  `accepted` and
`retired` are proof history; `phase` is the retained concrete control view. -/
structure State where
  phase : Phase
  accepted : List AcceptedTransaction
  retired : List AcceptedTransaction
  outputs : List Word
  deriving DecidableEq, Repr

def initial : State := ⟨.idle, [], [], []⟩

/-- One environment/controller interaction at the retained boundary. -/
inductive Input where
  | accept (transaction : AcceptedTransaction)
  | invalidOpcode
  | execute
  | tx (ready : Bool)
  | reset
  | disable
  deriving DecidableEq, Repr

/-- Executable transition relation. Inputs presented in a phase where the RTL
does not assert the corresponding ready signal leave the state unchanged. -/
def step (s : State) : Input → State
  | .reset | .disable => initial
  | .accept t => match s.phase with
      | .idle => { s with phase := .execute t, accepted := s.accepted ++ [t] }
      | _ => s
  | .invalidOpcode => match s.phase with
      | .idle => { s with phase := .fault }
      | _ => s
  | .execute => match s.phase with
      | .execute t => { s with phase := .transmit t 0 }
      | _ => s
  | .tx ready => match s.phase, ready with
      | .transmit t index, true =>
          if hlast : index.val = 15 then
            { phase := .idle
              accepted := s.accepted
              retired := s.retired ++ [t]
              outputs := s.outputs ++ [result t.opcode t.a t.b] }
          else
            { s with phase := .transmit t ⟨index.val + 1, by omega⟩ }
      | .fault, true => { s with phase := .idle }
      | _, _ => s

/-- Byte currently presented on `tx_data` at the successful-result boundary.
The index advances only on an accepted transfer, so this value is stable under
backpressure and covers all sixteen RTL response handshakes. -/
def txByte (s : State) : Option Byte :=
  match s.phase with
  | .transmit t index =>
      some (t.response.get ⟨index.val, by
        rw [response_length]
        exact index.isLt⟩)
  | .fault => some 0xe0#8
  | _ => none

def run (inputs : List Input) : State := inputs.foldl step initial

/-- The multi-transaction simulation invariant: retired transactions are an
accepted prefix; every retired output is exactly the Lean SET/XOR/MUL result;
and any result held under backpressure is the exact current transaction result.
-/
def Invariant (s : State) : Prop :=
  s.outputs = s.retired.map (fun t => result t.opcode t.a t.b) ∧
  match s.phase with
    | .idle | .fault => s.accepted = s.retired
    | .execute t | .transmit t _ => s.accepted = s.retired ++ [t]

theorem initial_invariant : Invariant initial := by
  simp [Invariant, initial]

/-- One-cycle inductiveness across acceptance, execution, RETIRE/IDLE, fault,
reset/disable, ignored input while busy, and arbitrary output backpressure. -/
theorem invariant_step (s : State) (input : Input) (h : Invariant s) :
    Invariant (step s input) := by
  rcases s with ⟨phase, accepted, retired, outputs⟩
  cases input with
  | reset => simp [Invariant, step, initial]
  | disable => simp [Invariant, step, initial]
  | accept transaction =>
      cases phase <;> simp_all [Invariant, step]
  | invalidOpcode =>
      cases phase <;> simp_all [Invariant, step]
  | execute =>
      cases phase <;> simp_all [Invariant, step]
  | tx ready =>
      cases phase <;> cases ready <;> simp_all [Invariant, step]
      rename_i transaction index
      by_cases hlast : index.val = 15
      · simp_all
      · simp_all

theorem foldl_invariant (s : State) (inputs : List Input) (h : Invariant s) :
    Invariant (inputs.foldl step s) := by
  induction inputs generalizing s with
  | nil => simpa using h
  | cons input rest ih =>
      simp only [List.foldl_cons]
      exact ih (step s input) (invariant_step s input h)

/-- Sound refinement for every finite, multi-transaction interaction trace. -/
theorem run_invariant (inputs : List Input) : Invariant (run inputs) := by
  exact foldl_invariant initial inputs initial_invariant

/-- Backpressure is a genuine stutter step: the current response byte, its
index, and all history remain stable, rather than being dropped or retired. -/
theorem backpressure_stable (s : State) : step s (.tx false) = s := by
  rcases s with ⟨phase, accepted, retired, outputs⟩
  cases phase <;> rfl

/-- Reset and disable abort every phase to the same clean IDLE state. -/
theorem reset_clears (s : State) : step s .reset = initial := rfl
theorem disable_clears (s : State) : step s .disable = initial := rfl

/-- Sixteen successful transfers, with a stall before the first one. -/
def transferResponse : List Input := .tx false :: List.replicate 16 (.tx true)

/-- Focused non-vacuity witness: two distinct accepted transactions really
retire, and the SET/XOR results are present in order after sixteen response
handshakes apiece. -/
example :
    let setTx : AcceptedTransaction := ⟨.set, 0x35#128, 0#128⟩
    let xorTx : AcceptedTransaction := ⟨.xor, 0xaa#128, 0x0f#128⟩
    let final := run ([.accept setTx, .execute] ++ transferResponse ++
      [.accept xorTx, .execute] ++ transferResponse)
    final.phase = .idle ∧ final.retired = [setTx, xorTx] ∧
      final.outputs = [0x35#128, 0xa5#128] := by
  decide

/-- One handshake cannot prematurely retire a 128-bit response. -/
example :
    let setTx : AcceptedTransaction := ⟨.set, 0x35#128, 0#128⟩
    (run [.accept setTx, .execute, .tx true]).phase = .transmit setTx 1 := by
  rfl

/-- MUL acceptance is non-vacuously reachable in the same transition system. -/
example :
    let mulTx : AcceptedTransaction := ⟨.mul, 1#128, 1#128⟩
    (run [.accept mulTx]).phase = .execute mulTx := by
  rfl

/-- Invalid decode reaches the fault phase and acknowledgement returns IDLE. -/
example :
    (run [.invalidOpcode]).phase = .fault ∧
    (run [.invalidOpcode, .tx false]).phase = .fault ∧
    (run [.invalidOpcode, .tx true]).phase = .idle := by
  decide

end LeanVMBMinCore.RTLTraceRefinement
