import Std.Tactic.BVDecide

/-!
Actual-width facts for leanVM-b's GHASH multiplication-by-x network.

Unlike the exhaustive multiplier theorem in `GF8.lean`, these statements use
all 128 bits.  They isolate the fixed linear transform instantiated in RTL and
justify the three-XOR tap count under the free-wire model.
-/

namespace LeanVMBMinCore.GHASH128

abbrev Word := BitVec 128

/-- leanVM-b's polynomial-basis multiplication by the generator x. -/
def xtime (x : Word) : Word :=
  (x <<< 1) ^^^ (if x.msb then 0x87#128 else 0#128)

/-- Reduction output bit 0 is the old carry directly, not an XOR gate. -/
theorem xtime_bit0_is_wire (x : Word) :
    (xtime x).getLsbD 0 = x.msb := by
  simp [xtime]
  bv_decide

/-- The three nontrivial reduction taps. `!=` is Boolean XOR. -/
theorem xtime_bit1_is_xor (x : Word) :
    (xtime x).getLsbD 1 = (x.getLsbD 0 != x.msb) := by
  simp [xtime]
  bv_decide

theorem xtime_bit2_is_xor (x : Word) :
    (xtime x).getLsbD 2 = (x.getLsbD 1 != x.msb) := by
  simp [xtime]
  bv_decide

theorem xtime_bit7_is_xor (x : Word) :
    (xtime x).getLsbD 7 = (x.getLsbD 6 != x.msb) := by
  simp [xtime]
  bv_decide

/-- An untapped output is just a shifted input wire. -/
theorem xtime_bit3_is_wire (x : Word) :
    (xtime x).getLsbD 3 = x.getLsbD 2 := by
  simp [xtime]
  bv_decide

/-- The defining reduction boundary x^128 = x^7+x^2+x+1. -/
theorem xtime_top_monomial :
    xtime (BitVec.twoPow 128 127) = 0x87#128 := by
  simp [xtime]
  bv_decide

/-- Multiplication by x is linear over field addition (bitwise XOR). -/
theorem xtime_xor_linear (a b : Word) :
    xtime (a ^^^ b) = xtime a ^^^ xtime b := by
  rw [xtime, xtime, xtime, BitVec.shiftLeft_xor_distrib]
  by_cases ha : a.msb <;> by_cases hb : b.msb
  · have cancel_middle (x y z : Word) : (x ^^^ y) ^^^ (z ^^^ y) = x ^^^ z := by
      rw [BitVec.xor_assoc x y (z ^^^ y), ← BitVec.xor_assoc y z y,
        BitVec.xor_comm y z, BitVec.xor_assoc, BitVec.xor_self, BitVec.xor_zero]
    simp [ha, hb]
    exact (cancel_middle _ (0x87#128) _).symm
  · simp [ha, hb]
    ac_rfl
  · simp [ha, hb]
    ac_rfl
  · simp [ha, hb]

end LeanVMBMinCore.GHASH128
