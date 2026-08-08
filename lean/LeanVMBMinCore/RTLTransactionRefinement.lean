import LeanVMBMinCore.RTLTraceRefinement

/-!
# Checked LSC-1u trace/transaction bridge

`RTLTraceRefinement` proves the byte-level retained-controller trace, while
`Transaction` proves functional STAGE/RETIRE atomicity.  This module supplies
the missing common relation: the ordered list retired by a payload-valid RTL
trace is the same list executed through the functional lifecycle.

The SystemVerilog transition system remains checked by the pinned SBY lanes;
Lean does not import an SV AST.  This module is therefore a checked
composition theorem at that documented boundary, not a single-kernel RTL
theorem.
-/

namespace LeanVMBMinCore.RTLTransactionRefinement

open LeanVMBMinCore
open RTLRefinement
open RTLTraceRefinement

abbrev Byte := BitVec 8

/-- Exact raw command decoder implemented by `src/lsc1u_core.sv`. -/
def decode : Byte → Option Opcode
  | 0x01#8 => some .xor
  | 0x02#8 => some .mul
  | 0x03#8 => some .set
  | _ => none

@[simp] theorem decode_opcode_byte (opcode : Opcode) :
    decode opcode.byte = some opcode := by
  cases opcode <;> rfl

theorem decoder_fault_precedence (byte : Byte) (h : decode byte = none) :
    RTLTraceRefinement.step RTLTraceRefinement.initial .invalidOpcode =
      { RTLTraceRefinement.initial with phase := .fault } ∧
    decode byte ≠ some .xor ∧ decode byte ≠ some .mul ∧
      decode byte ≠ some .set := by
  simp [RTLTraceRefinement.step, RTLTraceRefinement.initial, h]

/-- A retained command paired with the host transaction identifier used by
the functional STAGE/RETIRE lifecycle. -/
structure Command where
  txnId : Transaction.TxnId
  transaction : AcceptedTransaction
  deriving DecidableEq, Repr

/-- Execute one already decoded, byte-complete retained command through the
existing functional lifecycle. -/
def executeOne (model : Transaction.Model) (command : Command) :
    Transaction.Outcome :=
  let transition := toTransition model command.txnId command.transaction
  let staged := Transaction.step model (.stage transition)
  Transaction.step staged.model
    (.retire command.txnId
      (resultChecksum (result command.transaction.opcode
        command.transaction.a command.transaction.b)))

/-- Preconditions owned by the functional transaction foundation. -/
def Admissible (model : Transaction.Model) : Prop :=
  model.state = .idle ∧
    model.committed.pc.toNat < Transaction.indexLimit ∧
    model.committed.fp.toNat < Transaction.indexLimit

theorem executeOne_refines (model : Transaction.Model) (command : Command)
    (h : Admissible model) :
    let outcome := executeOne model command
    outcome.fault = none ∧ outcome.retired = true ∧
      outcome.model.state = .idle ∧
      outcome.model.committed.pc = model.committed.pc + 1 ∧
      outcome.model.committed.fp = model.committed.fp ∧
      outcome.model.committed.retireSeq = model.committed.retireSeq + 1 := by
  rcases command with ⟨txnId, transaction⟩
  rcases h with ⟨hidle, hpc, hfp⟩
  have hrefines := acceptedTransaction_refines model txnId transaction
    hidle hpc hfp
  simpa [executeOne] using
    ⟨hrefines.2.2.1, hrefines.2.2.2.1, hrefines.2.2.2.2.2.2.2,
      hrefines.2.2.2.2.1, hrefines.2.2.2.2.2.1,
      hrefines.2.2.2.2.2.2.1⟩

def execute : Transaction.Model → List Command → Transaction.Model
  | model, [] => model
  | model, command :: rest => execute (executeOne model command).model rest

/-- State-dependent validity permits arbitrary finite command lists while
requiring every actual STAGE to meet the transaction foundation's bounds. -/
def ValidSequence : Transaction.Model → List Command → Prop
  | _, [] => True
  | model, command :: rest =>
      Admissible model ∧ ValidSequence (executeOne model command).model rest

theorem execute_sequence_idle (model : Transaction.Model)
    (commands : List Command) (h : ValidSequence model commands)
    (hidle : model.state = .idle) :
    (execute model commands).state = .idle := by
  induction commands generalizing model with
  | nil => simpa [execute] using hidle
  | cons command rest ih =>
      rcases h with ⟨hadmissible, hrest⟩
      have hone := executeOne_refines model command hadmissible
      exact ih (executeOne model command).model hrest hone.2.2.1

/-- The checked relation tying the two proof foundations together. -/
def Related (rtl : RTLTraceRefinement.State) (commands : List Command) : Prop :=
  commands.map Command.transaction = rtl.retired ∧
    rtl.outputs = commands.map (fun command =>
      result command.transaction.opcode command.transaction.a
        command.transaction.b)

/-- **Canonical finite-sequence Lean/RTL transaction refinement.**

For every finite payload-valid retained interaction trace and every admissible
functional command sequence naming exactly its ordered retirements, the RTL
history is related to that sequence, every byte-serialized SET/XOR/GHASH-MUL
result occurs in order, and the composed functional lifecycle is back in
IDLE after matching RETIRE. -/
theorem finite_sequence_refines (inputs : List RTLTraceRefinement.Input)
    (commands : List Command)
    (htrace : RTLTraceRefinement.ValidTrace RTLTraceRefinement.initial inputs)
    (hcommands : commands.map Command.transaction =
      (RTLTraceRefinement.run inputs).retired)
    (hvalid : ValidSequence Transaction.initial commands) :
    Related (RTLTraceRefinement.run inputs) commands ∧
      (execute Transaction.initial commands).state = .idle := by
  have hinvariant := RTLTraceRefinement.run_invariant inputs htrace
  constructor
  · constructor
    · exact hcommands
    · rw [hinvariant.1, ← hcommands]
      simp [Function.comp_def]
  · exact execute_sequence_idle Transaction.initial commands hvalid rfl

theorem tx_backpressure_preserves_relation (rtl : RTLTraceRefinement.State)
    (commands : List Command) (h : Related rtl commands) :
    Related (RTLTraceRefinement.step rtl (.tx false)) commands := by
  simpa [RTLTraceRefinement.backpressure_stable] using h

theorem reset_disable_abort_pending (model : Transaction.Model) :
    (Transaction.step model .reset).model.state = .idle ∧
      (Transaction.step model .abort).model.state = .idle := by
  simp [Transaction.step, Transaction.initial]

/-! ## Prefix-by-prefix coupled state simulation -/

/-- Product state used for the prefix simulation. Transaction identifiers are
supplied by `txnIdOf`, just as the retained host supplies them in hardware. -/
structure CoupledState where
  rtl : RTLTraceRefinement.State
  functional : Transaction.Model
  deriving DecidableEq, Repr

def coupledInitial : CoupledState :=
  ⟨RTLTraceRefinement.initial, Transaction.initial⟩

/-- One synchronized retained/controller and functional lifecycle step. -/
def coupledStep (txnIdOf : AcceptedTransaction → Transaction.TxnId)
    (s : CoupledState) (input : RTLTraceRefinement.Input) : CoupledState :=
  match input with
  | .reset =>
      ⟨RTLTraceRefinement.step s.rtl .reset,
        (Transaction.step s.functional .reset).model⟩
  | .disable =>
      ⟨RTLTraceRefinement.step s.rtl .disable,
        (Transaction.step s.functional .abort).model⟩
  | .accept transaction =>
      match s.rtl.phase with
      | .idle =>
          ⟨RTLTraceRefinement.step s.rtl (.accept transaction),
            (Transaction.step s.functional
              (.stage (toTransition s.functional
                (txnIdOf transaction) transaction))).model⟩
      | _ => s
  | .tx true =>
      match s.rtl.phase with
      | .transmit transaction index =>
          if index.val = 15 then
            ⟨RTLTraceRefinement.step s.rtl (.tx true),
              (Transaction.step s.functional
                (.retire (txnIdOf transaction)
                  (resultChecksum
                    (result transaction.opcode transaction.a transaction.b)))).model⟩
          else ⟨RTLTraceRefinement.step s.rtl (.tx true), s.functional⟩
      | _ => ⟨RTLTraceRefinement.step s.rtl (.tx true), s.functional⟩
  | input => ⟨RTLTraceRefinement.step s.rtl input, s.functional⟩

/-- Lifecycle representation relation at every prefix. -/
def LifecycleRelated (txnIdOf : AcceptedTransaction → Transaction.TxnId)
    (s : CoupledState) : Prop :=
  match s.rtl.phase.pending, s.functional.state with
  | [], .idle => True
  | [transaction], .resultPending transition =>
      transition.txnId = txnIdOf transaction ∧
        transition.resultChecksum = resultChecksum
          (result transaction.opcode transaction.a transaction.b)
  | _, _ => False

def StateRelated (txnIdOf : AcceptedTransaction → Transaction.TxnId)
    (s : CoupledState) : Prop :=
  RTLTraceRefinement.Invariant s.rtl ∧ LifecycleRelated txnIdOf s

/-- Input validity combines exact payload-byte binding with the functional
STAGE preconditions at precisely those IDLE command-acceptance prefixes. -/
def CoupledValidInput (s : CoupledState) : RTLTraceRefinement.Input → Prop
  | .accept transaction =>
      RTLTraceRefinement.ValidInput s.rtl (.accept transaction) ∧
        (s.rtl.phase = .idle → Admissible s.functional)
  | input => RTLTraceRefinement.ValidInput s.rtl input

def CoupledValidTrace (txnIdOf : AcceptedTransaction → Transaction.TxnId) :
    CoupledState → List RTLTraceRefinement.Input → Prop
  | _, [] => True
  | s, input :: rest =>
      CoupledValidInput s input ∧
        CoupledValidTrace txnIdOf (coupledStep txnIdOf s input) rest

theorem coupledInitial_related
    (txnIdOf : AcceptedTransaction → Transaction.TxnId) :
    StateRelated txnIdOf coupledInitial := by
  exact ⟨RTLTraceRefinement.initial_invariant, by
    simp [LifecycleRelated, coupledInitial, RTLTraceRefinement.initial,
      RTLTraceRefinement.Phase.pending, Transaction.initial]⟩

theorem lifecycle_step (txnIdOf : AcceptedTransaction → Transaction.TxnId)
    (s : CoupledState) (input : RTLTraceRefinement.Input)
    (hrelated : LifecycleRelated txnIdOf s)
    (hvalid : CoupledValidInput s input) :
    LifecycleRelated txnIdOf (coupledStep txnIdOf s input) := by
  rcases s with ⟨⟨phase, accepted, retired, outputs⟩, functional⟩
  cases input with
  | reset => simp [coupledStep, LifecycleRelated, RTLTraceRefinement.step,
      RTLTraceRefinement.Phase.pending, Transaction.step, Transaction.initial]
  | disable => simp [coupledStep, LifecycleRelated, RTLTraceRefinement.step,
      Transaction.step]
  | invalidOpcode =>
      cases phase <;> simpa [coupledStep, LifecycleRelated,
        RTLTraceRefinement.step, RTLTraceRefinement.Phase.pending] using hrelated
  | accept transaction =>
      cases phase with
      | idle =>
          have hadmissible := hvalid.2 rfl
          rcases hadmissible with ⟨hidle, hpc, hfp⟩
          have hstage := acceptedTransaction_refines functional
            (txnIdOf transaction) transaction hidle hpc hfp
          simp only [coupledStep, RTLTraceRefinement.step, LifecycleRelated,
            RTLTraceRefinement.Phase.pending]
          rw [hstage.2.1]
          exact ⟨rfl, rfl⟩
      | receiveA _ _ => simpa [coupledStep, RTLTraceRefinement.step] using hrelated
      | receiveB _ _ => simpa [coupledStep, RTLTraceRefinement.step] using hrelated
      | execute _ => simpa [coupledStep, RTLTraceRefinement.step] using hrelated
      | transmit _ _ => simpa [coupledStep, RTLTraceRefinement.step] using hrelated
      | refill _ _ => simpa [coupledStep, RTLTraceRefinement.step] using hrelated
      | fault => simpa [coupledStep, RTLTraceRefinement.step] using hrelated
  | receive data =>
      cases phase with
      | receiveA transaction index =>
          rcases transaction with ⟨opcode, a, b⟩
          cases opcode <;> by_cases hlast : index.val = 15 <;>
            simp_all [coupledStep, LifecycleRelated, RTLTraceRefinement.step,
              RTLTraceRefinement.Phase.pending]
      | receiveB transaction index =>
          rcases transaction with ⟨opcode, a, b⟩
          cases opcode <;> by_cases hlast : index.val = 15 <;>
            simp_all [coupledStep, LifecycleRelated, RTLTraceRefinement.step,
              RTLTraceRefinement.Phase.pending]
      | idle => simpa [coupledStep, RTLTraceRefinement.step] using hrelated
      | execute _ => simpa [coupledStep, RTLTraceRefinement.step] using hrelated
      | transmit _ _ => simpa [coupledStep, RTLTraceRefinement.step] using hrelated
      | refill _ _ => simpa [coupledStep, RTLTraceRefinement.step] using hrelated
      | fault => simpa [coupledStep, RTLTraceRefinement.step] using hrelated
  | execute =>
      cases phase <;> simpa [coupledStep, LifecycleRelated,
        RTLTraceRefinement.step, RTLTraceRefinement.Phase.pending] using hrelated
  | refill =>
      cases phase <;> simpa [coupledStep, LifecycleRelated,
        RTLTraceRefinement.step, RTLTraceRefinement.Phase.pending] using hrelated
  | tx ready =>
      cases ready with
      | false => simpa [coupledStep, RTLTraceRefinement.backpressure_stable]
          using hrelated
      | true =>
          cases phase with
          | transmit transaction index =>
              by_cases hlast : index.val = 15
              · simp only [coupledStep, hlast, ↓reduceIte,
                  RTLTraceRefinement.step, LifecycleRelated,
                  RTLTraceRefinement.Phase.pending]
                cases hfunctional : functional.state with
                | idle =>
                    simp [LifecycleRelated, RTLTraceRefinement.Phase.pending,
                      hfunctional] at hrelated
                | resultPending transition =>
                    have hmatch : transition.txnId = txnIdOf transaction ∧
                        transition.resultChecksum = resultChecksum
                          (result transaction.opcode transaction.a
                            transaction.b) := by
                      simpa [LifecycleRelated, RTLTraceRefinement.Phase.pending,
                        hfunctional] using hrelated
                    simp [Transaction.step, hfunctional, hmatch.1, hmatch.2]
              · rcases transaction with ⟨opcode, a, b⟩
                cases opcode <;> simp_all [coupledStep, LifecycleRelated,
                  RTLTraceRefinement.step, RTLTraceRefinement.Phase.pending]
          | _ => simpa [coupledStep, LifecycleRelated,
              RTLTraceRefinement.step, RTLTraceRefinement.Phase.pending]
              using hrelated

theorem coupledStep_rtl
    (txnIdOf : AcceptedTransaction → Transaction.TxnId)
    (s : CoupledState) (input : RTLTraceRefinement.Input) :
    (coupledStep txnIdOf s input).rtl = RTLTraceRefinement.step s.rtl input := by
  cases input with
  | accept transaction =>
      cases hphase : s.rtl.phase <;>
        simp [coupledStep, hphase, RTLTraceRefinement.step]
  | tx ready =>
      cases ready with
      | false => rfl
      | true =>
          cases hphase : s.rtl.phase <;> simp [coupledStep, hphase]
          by_cases hlast : ‹Fin 16›.val = 15 <;>
            simp [hlast]
  | _ => rfl

theorem stateRelated_step
    (txnIdOf : AcceptedTransaction → Transaction.TxnId)
    (s : CoupledState) (input : RTLTraceRefinement.Input)
    (hrelated : StateRelated txnIdOf s)
    (hvalid : CoupledValidInput s input) :
    StateRelated txnIdOf (coupledStep txnIdOf s input) := by
  constructor
  · rw [coupledStep_rtl]
    exact RTLTraceRefinement.invariant_step s.rtl input hrelated.1
  · exact lifecycle_step txnIdOf s input hrelated.2 hvalid

def coupledRun (txnIdOf : AcceptedTransaction → Transaction.TxnId)
    (inputs : List RTLTraceRefinement.Input) : CoupledState :=
  inputs.foldl (coupledStep txnIdOf) coupledInitial

/-- Prefix-sensitive arbitrary-finite simulation theorem. This is the central
state/transaction refinement: every valid prefix maintains both exact ordered
results and the synchronized STAGE/pending/RETIRE-or-abort lifecycle. -/
theorem coupled_finite_trace_refines
    (txnIdOf : AcceptedTransaction → Transaction.TxnId)
    (inputs : List RTLTraceRefinement.Input)
    (hvalid : CoupledValidTrace txnIdOf coupledInitial inputs) :
    StateRelated txnIdOf (coupledRun txnIdOf inputs) := by
  have fold_related (rest : List RTLTraceRefinement.Input) (s : CoupledState)
      (hs : StateRelated txnIdOf s)
      (hv : CoupledValidTrace txnIdOf s rest) :
      StateRelated txnIdOf (rest.foldl (coupledStep txnIdOf) s) := by
    induction rest generalizing s with
    | nil => simpa using hs
    | cons input tail ih =>
        exact ih (coupledStep txnIdOf s input)
          (stateRelated_step txnIdOf s input hs hv.1) hv.2
  exact fold_related inputs coupledInitial (coupledInitial_related txnIdOf) hvalid

/-- Non-vacuity: every implemented transaction reaches the synchronized
receive/pending state from the concrete initial state. -/
theorem coupled_accept_reachable
    (txnIdOf : AcceptedTransaction → Transaction.TxnId)
    (transaction : AcceptedTransaction) :
    StateRelated txnIdOf
      (coupledStep txnIdOf coupledInitial (.accept transaction)) := by
  apply stateRelated_step txnIdOf coupledInitial (.accept transaction)
  · exact coupledInitial_related txnIdOf
  · constructor
    · trivial
    · intro _
      simp [Admissible, coupledInitial, Transaction.initial,
        Transaction.indexLimit]

/-- Non-vacuity: enable-disable after a reachable acceptance synchronously
aborts both retained and functional pending state back to IDLE. -/
theorem coupled_disable_abort_reachable
    (txnIdOf : AcceptedTransaction → Transaction.TxnId)
    (transaction : AcceptedTransaction) :
    StateRelated txnIdOf
      (coupledStep txnIdOf
        (coupledStep txnIdOf coupledInitial (.accept transaction))
        .disable) := by
  apply stateRelated_step
  · exact coupled_accept_reachable txnIdOf transaction
  · trivial

/-- Lifecycle mutation falsifier: changing a successful matching retirement
to `retired = false` contradicts the functional refinement theorem. -/
theorem retired_false_mutation_falsified
    (model : Transaction.Model) (command : Command)
    (h : Admissible model) :
    (executeOne model command).retired ≠ false := by
  have hrefines := executeOne_refines model command h
  simp [hrefines.2.1]

/-- Reachability/non-vacuity: a concrete SET transaction stages and retires. -/
example :
    let command : Command := ⟨7, ⟨.set, 0x0123456789abcdef#128, 0⟩⟩
    (executeOne Transaction.initial command).retired = true ∧
      (executeOne Transaction.initial command).model.state = .idle := by
  decide

/-- Decode mutation witness: exchanging any implemented opcode is observable. -/
example : decode 0x01#8 ≠ some .mul ∧ decode 0x02#8 ≠ some .set := by
  decide

end LeanVMBMinCore.RTLTransactionRefinement
