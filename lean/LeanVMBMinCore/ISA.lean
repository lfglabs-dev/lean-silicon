import LeanVMBMinCore.GF8

/-!
A deliberately small scalar-ISA refinement model.  It proves the datapath
boundary implemented in the first RTL: XOR, native field multiplication, SET,
and the zero test used by JUMP.  Memory sequencing and DEREF reconciliation are
left outside this first proof boundary and specified in docs/FULL_CORE.md.
-/

namespace LeanVMBMinCore.ISA

open LeanVMBMinCore.GF8

abbrev Word := BitVec 8
abbrev ValueMem := Nat → Word

structure State where
  pc : Nat
  fp : Nat
  mem : ValueMem

inductive Op where
  | xorOp (a b c : Nat)
  | mulOp (a b c : Nat)
  | setOp (o : Nat) (k : Word)
  | jumpOp (oc od of_ : Nat)

/-- Integer physical address corresponding to an fp-relative reference. -/
def localAddr (fp offset : Nat) : Nat := fp + offset

def write (m : ValueMem) (address : Nat) (value : Word) : ValueMem :=
  fun query => if query = address then value else m query

/-- Mathematical scalar transition; multiplication uses the schoolbook spec. -/
def specStep (op : Op) (s : State) : State :=
  match op with
  | .xorOp a b c =>
      let va := s.mem (localAddr s.fp a)
      let vb := s.mem (localAddr s.fp b)
      { s with
        pc := s.pc + 1
        mem := write s.mem (localAddr s.fp c) (va ^^^ vb) }
  | .mulOp a b c =>
      let va := s.mem (localAddr s.fp a)
      let vb := s.mem (localAddr s.fp b)
      { s with
        pc := s.pc + 1
        mem := write s.mem (localAddr s.fp c) (specMul va vb) }
  | .setOp o k =>
      { s with
        pc := s.pc + 1
        mem := write s.mem (localAddr s.fp o) k }
  | .jumpOp oc od of_ =>
      let condition := s.mem (localAddr s.fp oc)
      if condition = 0#8 then
        { s with pc := s.pc + 1 }
      else
        { s with
          pc := (s.mem (localAddr s.fp od)).toNat
          fp := (s.mem (localAddr s.fp of_)).toNat }

/-- Hardware transition; multiplication uses the serial circuit algorithm. -/
def hardwareStep (op : Op) (s : State) : State :=
  match op with
  | .xorOp a b c =>
      let va := s.mem (localAddr s.fp a)
      let vb := s.mem (localAddr s.fp b)
      { s with
        pc := s.pc + 1
        mem := write s.mem (localAddr s.fp c) (va ^^^ vb) }
  | .mulOp a b c =>
      let va := s.mem (localAddr s.fp a)
      let vb := s.mem (localAddr s.fp b)
      { s with
        pc := s.pc + 1
        mem := write s.mem (localAddr s.fp c) (serialMul va vb) }
  | .setOp o k =>
      { s with
        pc := s.pc + 1
        mem := write s.mem (localAddr s.fp o) k }
  | .jumpOp oc od of_ =>
      let condition := s.mem (localAddr s.fp oc)
      if condition = 0#8 then
        { s with pc := s.pc + 1 }
      else
        { s with
          pc := (s.mem (localAddr s.fp od)).toNat
          fp := (s.mem (localAddr s.fp of_)).toNat }

/-- Instruction-level refinement for the simplified scalar model. -/
theorem hardwareStep_refines (op : Op) (s : State) :
    hardwareStep op s = specStep op s := by
  cases op <;> simp [hardwareStep, specStep, serialMul_correct]

end LeanVMBMinCore.ISA
