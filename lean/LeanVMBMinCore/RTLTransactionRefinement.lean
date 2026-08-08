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
