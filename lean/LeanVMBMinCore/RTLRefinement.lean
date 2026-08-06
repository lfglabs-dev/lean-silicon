import LeanVMBMinCore.ByteSerialization
import LeanVMBMinCore.GHASH128
import LeanVMBMinCore.Transaction

/-!
# LSC-1u transaction refinement boundary

This module is the Lean side of the compositional LSC-1u proof.  It gives a
single-transaction abstraction of the ready/valid RTL: an accepted opcode and
its complete operands produce sixteen least-significant-byte-first response
beats and one retirement event.  The existing SystemVerilog proofs establish
that the concrete registers and handshakes implement this abstraction under
arbitrary stalls, reset, and abort.

The opcode values below deliberately follow `src/lsc1u_core.sv`:

* `0x01` -- XOR
* `0x02` -- GF(2^128) MUL
* `0x03` -- SET

The theorem `acceptedTransaction_refines` connects a successful instance of
that abstraction to two actual `Transaction.step` calls: atomic staging and a
matching, exactly-once retirement.  This is a bounded refinement (one opcode,
one response, one retirement), not yet a cycle-by-cycle simulation theorem.
-/

namespace LeanVMBMinCore.RTLRefinement

open LeanVMBMinCore

abbrev Byte := BitVec 8
abbrev Word := BitVec 128

/-- The three commands accepted by the shipped LSC-1u decoder. -/
inductive Opcode where
  | xor
  | mul
  | set
  deriving DecidableEq, Repr

/-- Concrete byte presented to the RTL command channel. -/
def Opcode.byte : Opcode → Byte
  | .xor => 0x01#8
  | .mul => 0x02#8
  | .set => 0x03#8

/-- Architectural result of one complete LSC-1u command. -/
def result : Opcode → Word → Word → Word
  | .xor, a, b => a ^^^ b
  | .mul, a, b => GHASH128.mul a b
  | .set, a, _ => a

/-- Complete accepted transaction at the retained RTL boundary.  `b` is
ignored for SET, matching its one-operand wire protocol. -/
structure AcceptedTransaction where
  opcode : Opcode
  a : Word
  b : Word
  deriving DecidableEq, Repr

/-- Alternate bytes from the two XOR operands, as the RTL accepts
`A0,B0,...,A15,B15`. -/
def interleave : List Byte → List Byte → List Byte
  | a :: as, b :: bs => a :: b :: interleave as bs
  | _, _ => []

/-- Input payload bytes after the opcode, in the order accepted by RTL. -/
def AcceptedTransaction.payload (t : AcceptedTransaction) : List Byte :=
  match t.opcode with
  | .xor => interleave
      (ByteSerialization.serialize t.a) (ByteSerialization.serialize t.b)
  | .mul => ByteSerialization.serialize t.a ++ ByteSerialization.serialize t.b
  | .set => ByteSerialization.serialize t.a

/-- The sixteen response beats observed at successful completion. -/
def AcceptedTransaction.response (t : AcceptedTransaction) : List Byte :=
  ByteSerialization.serialize (result t.opcode t.a t.b)

/-- XOR and MUL accept 32 payload bytes; SET accepts 16. -/
theorem payload_length (t : AcceptedTransaction) :
    t.payload.length = match t.opcode with
      | .xor => 32
      | .mul => 32
      | .set => 16 := by
  rcases t with ⟨op, a, b⟩
  cases op <;>
    simp [AcceptedTransaction.payload, interleave,
      ByteSerialization.serialize, ByteSerialization.beats,
      ByteSerialization.emitBytes]

/-- The transaction layer carries a compact checksum rather than the complete
128-bit response.  This bridge uses the low 32 result bits. -/
def resultChecksum (w : Word) : Transaction.ResultChecksum :=
  UInt32.ofNat w.toNat

/-- Translation from an accepted RTL transaction to the transition staged by
the functional transaction model. -/
def toTransition (m : Transaction.Model) (txnId : Transaction.TxnId)
    (t : AcceptedTransaction) : Transaction.Transition := {
  txnId := txnId
  currentPc := m.committed.pc
  currentFp := m.committed.fp
  nextPc := m.committed.pc + 1
  nextFp := m.committed.fp
  resultChecksum := resultChecksum (result t.opcode t.a t.b)
}

/-- A full response always consists of exactly the sixteen response transfers
used by `lsc1u_core`. -/
theorem response_length (t : AcceptedTransaction) : t.response.length = 16 := by
  simp [AcceptedTransaction.response, ByteSerialization.serialize,
    ByteSerialization.beats]

/-- The response stream reconstructs the operation's mathematical result.
This pins the bridge to the RTL's least-significant-byte-first convention. -/
theorem response_deserializes (t : AcceptedTransaction) :
    ByteSerialization.deserialize t.response = result t.opcode t.a t.b := by
  simp [AcceptedTransaction.response, ByteSerialization.deserialize_serialize]

/-- The decoder bytes are distinct, so the three semantic cases cannot be
silently exchanged at the bridge boundary. -/
theorem opcode_bytes_distinct :
    Opcode.xor.byte ≠ Opcode.mul.byte ∧
    Opcode.xor.byte ≠ Opcode.set.byte ∧
    Opcode.mul.byte ≠ Opcode.set.byte := by
  decide

/-- **Bounded Lean/RTL transaction refinement.**

For an idle functional model whose current indices are in range, every
successfully accepted LSC-1u command stages the translated transition without
a fault.  Acceptance of its mathematically specified response then performs
one matching retirement, advances `pc`, preserves `fp`, records the result
checksum, and returns to idle. -/
theorem acceptedTransaction_refines (m : Transaction.Model)
    (txnId : Transaction.TxnId) (t : AcceptedTransaction)
    (hidle : m.state = .idle)
    (hpc : m.committed.pc.toNat < Transaction.indexLimit)
    (hfp : m.committed.fp.toNat < Transaction.indexLimit) :
    let tr := toTransition m txnId t
    let staged := Transaction.step m (.stage tr)
    let retired := Transaction.step staged.model
      (.retire txnId (resultChecksum (result t.opcode t.a t.b)))
    staged.fault = none ∧
      staged.model.state = .resultPending tr ∧
      retired.fault = none ∧
      retired.retired = true ∧
      retired.model.committed.pc = m.committed.pc + 1 ∧
      retired.model.committed.fp = m.committed.fp ∧
      retired.model.committed.retireSeq = m.committed.retireSeq + 1 ∧
      retired.model.state = .idle := by
  have hmatch : Transaction.stateMatches m (toTransition m txnId t) = true := by
    simp [Transaction.stateMatches, toTransition]
  have hrange :
      Transaction.currentIndicesInRange (toTransition m txnId t) = true := by
    simp [Transaction.currentIndicesInRange, toTransition, hpc, hfp]
  dsimp only
  rw [Transaction.stage_is_atomic m (toTransition m txnId t) hidle hrange hmatch]
  simp [Transaction.step, toTransition]

/-- Specialization for the RTL `0x01` XOR command. -/
theorem xor_transaction_refines (m : Transaction.Model)
    (txnId : Transaction.TxnId) (a b : Word)
    (hidle : m.state = .idle)
    (hpc : m.committed.pc.toNat < Transaction.indexLimit)
    (hfp : m.committed.fp.toNat < Transaction.indexLimit) :
    (Transaction.step m
      (.stage (toTransition m txnId ⟨.xor, a, b⟩))).fault = none := by
  have h := acceptedTransaction_refines m txnId ⟨.xor, a, b⟩ hidle hpc hfp
  exact h.1

/-- Specialization for the RTL `0x02` MUL command. -/
theorem mul_transaction_refines (m : Transaction.Model)
    (txnId : Transaction.TxnId) (a b : Word)
    (hidle : m.state = .idle)
    (hpc : m.committed.pc.toNat < Transaction.indexLimit)
    (hfp : m.committed.fp.toNat < Transaction.indexLimit) :
    (Transaction.step m
      (.stage (toTransition m txnId ⟨.mul, a, b⟩))).fault = none := by
  have h := acceptedTransaction_refines m txnId ⟨.mul, a, b⟩ hidle hpc hfp
  exact h.1

/-- Specialization for the RTL `0x03` SET command. -/
theorem set_transaction_refines (m : Transaction.Model)
    (txnId : Transaction.TxnId) (value : Word)
    (hidle : m.state = .idle)
    (hpc : m.committed.pc.toNat < Transaction.indexLimit)
    (hfp : m.committed.fp.toNat < Transaction.indexLimit) :
    (Transaction.step m
      (.stage (toTransition m txnId ⟨.set, value, 0⟩))).fault = none := by
  have h := acceptedTransaction_refines m txnId ⟨.set, value, 0⟩ hidle hpc hfp
  exact h.1

end LeanVMBMinCore.RTLRefinement
