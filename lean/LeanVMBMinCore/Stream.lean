import Std.Tactic.BVDecide

/-!
A functional model of the optimized atomic byte-stream commands. It is separate
from the cycle-count proof: this file checks byte ordering and values, while
`Optimality.lean` checks the accepted-beat lower bounds.
-/

namespace LeanVMBMinCore.Stream

abbrev Byte := BitVec 8

/-- Wire representation expected by XOR128: A0,B0,A1,B1,... -/
def interleave : List Byte → List Byte → List Byte
  | a :: as, b :: bs => a :: b :: interleave as bs
  | _, _ => []

/-- Transaction parser/transform implemented by the XOR FSM. -/
def consumeXor : List Byte → List Byte
  | a :: b :: rest => (a ^^^ b) :: consumeXor rest
  | _ => []

/-- Direct lane-wise functional specification. -/
def xorSpec : List Byte → List Byte → List Byte
  | a :: as, b :: bs => (a ^^^ b) :: xorSpec as bs
  | _, _ => []

/-- The interleaved wire protocol computes exactly the lane-wise XOR spec. -/
theorem xorProtocol_correct (as bs : List Byte) :
    consumeXor (interleave as bs) = xorSpec as bs := by
  induction as generalizing bs with
  | nil => cases bs <;> rfl
  | cons a as ih =>
      cases bs with
      | nil => rfl
      | cons b bs =>
          simp [interleave, consumeXor, xorSpec, ih]

/-- SET's optimized stream is exactly the identity transform. -/
def setStream (input : List Byte) : List Byte := input

@[simp] theorem setStream_correct (input : List Byte) : setStream input = input := rfl

/-- Boolean transition used by the byte-stream NONZERO accumulator. -/
def nonzeroStep (seen : Bool) (byte : Byte) : Bool :=
  seen || byte != 0#8

/-- The final-byte combinational form equals one ordinary accumulator step. -/
theorem nonzero_final_byte (seen : Bool) (byte : Byte) :
    (seen || byte != 0#8) = nonzeroStep seen byte := rfl

end LeanVMBMinCore.Stream
