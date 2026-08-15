/-!
# Finite host-prepared boundary receipt

This module checks the shape of the checked LSC-1 host workload receipt.  The
receipt itself is generated from a real `HostRuntime` run and authored-RTL
responses; this file contains no RTL observations and is not an unbounded
refinement theorem.
-/

namespace LeanVMBMinCore.HostPreparedBoundary

inductive Operation where
  | set | xor | mul | derefCell | derefPc | derefFp | jump | blake3
  deriving DecidableEq, Repr

structure StepFact where
  operation : Operation
  suppliedCellsMatchHost : Bool
  resultAppliedAfterRetire : Bool
  rtlBytesMatchModel : Bool
  deriving DecidableEq, Repr

def expectedOperations : List Operation :=
  [.set, .set, .xor, .set, .xor, .set, .mul, .set, .xor, .set,
   .set, .set, .jump]

def receiptValid (facts : List StepFact) : Bool :=
  facts.map (·.operation) == expectedOperations &&
  facts.all (·.suppliedCellsMatchHost) &&
  facts.all (·.resultAppliedAfterRetire) &&
  facts.all (·.rtlBytesMatchModel)

structure BoundaryEvidence (facts : List StepFact) : Prop where
  exactFiniteReceipt : receiptValid facts = true

theorem receiptHolds (facts : List StepFact)
    (h : receiptValid facts = true) : BoundaryEvidence facts :=
  ⟨h⟩

end LeanVMBMinCore.HostPreparedBoundary
