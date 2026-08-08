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
* RECEIVE_A/RECEIVE_B bind every accepted payload byte to the transaction and
  retain SET/XOR's required receive/result-transfer interleaving;
* MUL execution computes the operation result specified by
  `RTLRefinement.result` after all sixteen operand lanes;
* TRANSMIT exposes all sixteen least-significant-byte-first response beats,
  holds the current byte stable while `tx_ready = false`, and commits exactly
  once only after the sixteenth accepted transfer;
* MUL REFILL retains the mandatory `tx_valid = false` cycle between beats;
* reset and `ena = false` abort all in-flight work and return to IDLE.

The model collapses MUL's per-byte bit cycles into the `execute` transition,
but does not abstract or reorder payload-byte or response-byte transfers.
Their concrete correspondence is proved separately by
`formal/lsc1u_compositional_refinement.sby` and
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
  | receiveA (transaction : AcceptedTransaction) (index : Fin 16)
  | receiveB (transaction : AcceptedTransaction) (index : Fin 16)
  | execute (transaction : AcceptedTransaction)
  | transmit (transaction : AcceptedTransaction) (index : Fin 16)
  | refill (transaction : AcceptedTransaction) (index : Fin 16)
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
  | receive (data : Byte)
  | execute
  | refill
  | tx (ready : Bool)
  | reset
  | disable
  deriving DecidableEq, Repr

/-- Executable transition relation. Inputs presented in a phase where the RTL
does not assert the corresponding ready signal leave the state unchanged. -/
def step (s : State) : Input → State
  | .reset | .disable =>
      { phase := .idle, accepted := s.retired,
        retired := s.retired, outputs := s.outputs }
  | .accept t => match s.phase with
      | .idle => { s with phase := .receiveA t 0, accepted := s.accepted ++ [t] }
      | _ => s
  | .invalidOpcode => match s.phase with
      | .idle => { s with phase := .fault }
      | _ => s
  | .receive data => match s.phase with
      | .receiveA t index =>
          match t.opcode with
          | .set => { s with phase := .transmit t index }
          | .xor => { s with phase := .receiveB t index }
          | .mul =>
              if hlast : index.val = 15 then
                { s with phase := .receiveB t 0 }
              else
                { s with phase := .receiveA t ⟨index.val + 1, by omega⟩ }
      | .receiveB t index =>
          match t.opcode with
          | .xor => { s with phase := .transmit t index }
          | .mul =>
              if hlast : index.val = 15 then
                { s with phase := .execute t }
              else
                { s with phase := .receiveB t ⟨index.val + 1, by omega⟩ }
          | .set => s
      | _ => s
  | .execute => match s.phase with
      | .execute t => { s with phase := .transmit t 0 }
      | _ => s
  | .refill => match s.phase with
      | .refill t index => { s with phase := .transmit t index }
      | _ => s
  | .tx ready => match s.phase, ready with
      | .transmit t index, true =>
          if hlast : index.val = 15 then
            { phase := .idle
              accepted := s.accepted
              retired := s.retired ++ [t]
              outputs := s.outputs ++ [result t.opcode t.a t.b] }
          else
            match t.opcode with
            | .set | .xor =>
                { s with phase := .receiveA t ⟨index.val + 1, by omega⟩ }
            | .mul =>
                { s with phase := .refill t ⟨index.val + 1, by omega⟩ }
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

/-- Payload-side validity binds each receive event to the byte expected by the
accepted transaction. Other inputs are valid in every phase (and may stutter). -/
def ValidInput (s : State) : Input → Prop
  | .receive data => match s.phase with
      | .receiveA t index => data = ByteSerialization.byteAt t.a index.val
      | .receiveB t index => data = ByteSerialization.byteAt t.b index.val
      | _ => False
  | _ => True

/-- State-dependent validity of a projected finite interaction trace. -/
def ValidTrace : State → List Input → Prop
  | _, [] => True
  | s, input :: rest => ValidInput s input ∧ ValidTrace (step s input) rest

/-- The outstanding transaction represented by a retained control phase. -/
@[simp] def Phase.pending : Phase → List AcceptedTransaction
  | .idle | .fault => []
  | .receiveA t _ | .receiveB t _ | .execute t |
      .transmit t _ | .refill t _ => [t]

/-- The multi-transaction simulation invariant: retired transactions are an
accepted prefix and every retired output is exactly the Lean SET/XOR/MUL
result. The phase contributes at most one accepted, outstanding transaction. -/
def Invariant (s : State) : Prop :=
  s.outputs = s.retired.map (fun t => result t.opcode t.a t.b) ∧
  s.accepted = s.retired ++ s.phase.pending

theorem initial_invariant : Invariant initial := by
  simp [Invariant, Phase.pending, initial]

theorem receive_preserves_observation (s : State) (data : Byte) :
    let s' := step s (.receive data)
    s'.accepted = s.accepted ∧ s'.retired = s.retired ∧
      s'.outputs = s.outputs ∧ s'.phase.pending = s.phase.pending := by
  rcases s with ⟨phase, accepted, retired, outputs⟩
  cases phase with
  | receiveA transaction index =>
      rcases transaction with ⟨opcode, a, b⟩
      cases opcode <;> by_cases hlast : index.val = 15 <;>
        simp [step, Phase.pending, hlast]
  | receiveB transaction index =>
      rcases transaction with ⟨opcode, a, b⟩
      cases opcode <;> by_cases hlast : index.val = 15 <;>
        simp [step, Phase.pending, hlast]
  | idle => simp [step, Phase.pending]
  | execute _ => simp [step, Phase.pending]
  | transmit _ _ => simp [step, Phase.pending]
  | refill _ _ => simp [step, Phase.pending]
  | fault => simp [step, Phase.pending]

/-- One-cycle inductiveness across acceptance, execution, RETIRE/IDLE, fault,
reset/disable, ignored input while busy, and arbitrary output backpressure. -/
theorem invariant_step (s : State) (input : Input) (h : Invariant s) :
    Invariant (step s input) := by
  rcases s with ⟨phase, accepted, retired, outputs⟩
  cases input with
  | reset => simp_all [Invariant, Phase.pending, step]
  | disable => simp_all [Invariant, Phase.pending, step]
  | accept transaction =>
      cases phase <;> simp_all [Invariant, Phase.pending, step]
  | invalidOpcode =>
      cases phase <;> simp_all [Invariant, Phase.pending, step]
  | receive data =>
      have hp := receive_preserves_observation
        { phase := phase, accepted := accepted, retired := retired, outputs := outputs } data
      rcases hp with ⟨ha, hr, ho, hp⟩
      simp only [Invariant] at h ⊢
      rw [ha, hr, ho, hp]
      exact h
  | execute =>
      cases phase <;> simp_all [Invariant, Phase.pending, step]
  | refill =>
      cases phase <;> simp_all [Invariant, Phase.pending, step]
  | tx ready =>
      cases ready with
      | false => simpa [step] using h
      | true =>
          cases phase with
          | transmit transaction index =>
              by_cases hlast : index.val = 15
              · simp_all [Invariant, Phase.pending, step, List.map_append]
              · rcases transaction with ⟨opcode, a, b⟩
                cases opcode <;>
                  simp_all [Invariant, Phase.pending, step]
          | _ => simpa [Invariant, Phase.pending, step] using h

theorem foldl_invariant (s : State) (inputs : List Input) (h : Invariant s) :
    Invariant (inputs.foldl step s) := by
  induction inputs generalizing s with
  | nil => simpa using h
  | cons input rest ih =>
      simp only [List.foldl_cons]
      exact ih (step s input) (invariant_step s input h)

/-- Sound refinement for every finite, payload-valid multi-transaction trace. -/
theorem run_invariant (inputs : List Input) (_ : ValidTrace initial inputs) :
    Invariant (run inputs) := by
  exact foldl_invariant initial inputs initial_invariant

/-- Backpressure is a genuine stutter step: the current response byte, its
index, and all history remain stable, rather than being dropped or retired. -/
theorem backpressure_stable (s : State) : step s (.tx false) = s := by
  rcases s with ⟨phase, accepted, retired, outputs⟩
  cases phase <;> rfl

/-- Reset and disable abort the outstanding transaction and return to IDLE,
while ghost history retains every response already observed in the trace. -/
theorem reset_aborts (s : State) :
    step s .reset = ⟨.idle, s.retired, s.retired, s.outputs⟩ := rfl
theorem disable_aborts (s : State) :
    step s .disable = ⟨.idle, s.retired, s.retired, s.outputs⟩ := rfl

/-- Non-vacuity: every transaction can enter its first byte-receive phase. -/
example (t : AcceptedTransaction) :
    (run [.accept t]).phase = .receiveA t 0 := rfl

/-- The validity premise binds a receive event to the exact operand byte. -/
example (t : AcceptedTransaction) (index : Fin 16) (data : Byte) :
    ValidInput { initial with phase := .receiveA t index } (.receive data) ↔
      data = ByteSerialization.byteAt t.a index.val := Iff.rfl

/-- Non-vacuity: a final valid response beat performs exactly one retirement. -/
example (t : AcceptedTransaction) :
    step { phase := .transmit t ⟨15, by omega⟩
           accepted := [t], retired := [], outputs := [] } (.tx true) =
      { phase := .idle, accepted := [t], retired := [t]
        outputs := [result t.opcode t.a t.b] } := by
  simp [step]

end LeanVMBMinCore.RTLTraceRefinement
