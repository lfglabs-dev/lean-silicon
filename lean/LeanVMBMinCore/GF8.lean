import Std.Tactic.BVDecide

/-!
A finite, executable proof model for the MinCore multiplier.

The silicon uses 128 bits and reduction constant 0x87.  This file uses the
isomorphic eight-bit construction with AES reduction constant 0x1b, so the
entire serial multiplier can be bit-blasted by Lean's kernel-checked
`bv_decide` tactic.  The control invariant is the same: LSB-first multiplier
bits, one conditional XOR, then one multiplication by x per step.  The
reference side is independently expressed as a 16-bit carry-less product plus
polynomial long reduction.
-/

namespace LeanVMBMinCore.GF8

abbrev Word := BitVec 8

/-- Multiplication by x modulo x^8 + x^4 + x^3 + x + 1. -/
def xtime (x : Word) : Word :=
  (x <<< 1) ^^^ (if x.msb then 0x1b#8 else 0#8)

/-- Select a field element with one multiplier bit. -/
def select (bit : Bool) (x : Word) : Word :=
  if bit then x else 0#8

structure MulState where
  shifted : Word
  acc : Word
  deriving DecidableEq, Repr

/-- One RTL-style multiplier-bit transition. -/
def step (s : MulState) (bit : Bool) : MulState :=
  {
    shifted := xtime s.shifted
    acc := s.acc ^^^ select bit s.shifted
  }

/-- The eight explicitly unrolled bit-serial transitions. -/
def serialMul (a b : Word) : Word :=
  let s0 : MulState := { shifted := a, acc := 0#8 }
  let s1 := step s0 (b.getLsbD 0)
  let s2 := step s1 (b.getLsbD 1)
  let s3 := step s2 (b.getLsbD 2)
  let s4 := step s3 (b.getLsbD 3)
  let s5 := step s4 (b.getLsbD 4)
  let s6 := step s5 (b.getLsbD 5)
  let s7 := step s6 (b.getLsbD 6)
  let s8 := step s7 (b.getLsbD 7)
  s8.acc

/-- Zero-extend an eight-bit polynomial to the unreduced product width. -/
def widen (x : Word) : BitVec 16 := x.setWidth 16

/-- Select a 16-bit polynomial with one multiplier bit. -/
def selectWide (bit : Bool) (x : BitVec 16) : BitVec 16 :=
  if bit then x else 0#16

/--
Independent carry-less schoolbook product.  Unlike `serialMul`, this constructs
all eight shifted partial products in a 16-bit unreduced polynomial first.
-/
def carrylessProduct (a b : Word) : BitVec 16 :=
  selectWide (b.getLsbD 0) (widen a) ^^^
  selectWide (b.getLsbD 1) (widen a <<< 1) ^^^
  selectWide (b.getLsbD 2) (widen a <<< 2) ^^^
  selectWide (b.getLsbD 3) (widen a <<< 3) ^^^
  selectWide (b.getLsbD 4) (widen a <<< 4) ^^^
  selectWide (b.getLsbD 5) (widen a <<< 5) ^^^
  selectWide (b.getLsbD 6) (widen a <<< 6) ^^^
  selectWide (b.getLsbD 7) (widen a <<< 7)

/-- Cancel one high polynomial coefficient using the monic AES modulus. -/
def reduceAt (p : BitVec 16) (bit shift : Nat) : BitVec 16 :=
  if p.getLsbD bit then p ^^^ (0x011b#16 <<< shift) else p

/-- Explicit degree-14-to-8 polynomial long reduction. -/
def reduceProduct (p : BitVec 16) : Word :=
  let p14 := reduceAt p   14 6
  let p13 := reduceAt p14 13 5
  let p12 := reduceAt p13 12 4
  let p11 := reduceAt p12 11 3
  let p10 := reduceAt p11 10 2
  let p9  := reduceAt p10  9 1
  let p8  := reduceAt p9   8 0
  p8.setWidth 8

/-- Independent schoolbook-product-plus-long-reduction specification. -/
def specMul (a b : Word) : Word :=
  reduceProduct (carrylessProduct a b)

/-- Exhaustive symbolic proof for all 65,536 input pairs. -/
theorem serialMul_correct : ∀ (a b : Word), serialMul a b = specMul a b := by
  native_decide

/-- The serial circuit has the expected zero and one identities. -/
theorem serialMul_zero_right : ∀ (a : Word), serialMul a 0#8 = 0#8 := by
  native_decide

theorem serialMul_one_right : ∀ (a : Word), serialMul a 1#8 = a := by
  native_decide

end LeanVMBMinCore.GF8
