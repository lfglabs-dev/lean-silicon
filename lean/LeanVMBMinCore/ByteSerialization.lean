/-!
# 128-bit byte serialization: ordering and round-trip

A functional model of the two 16-beat byte-serialization paths in
`asic_core/rtl/gf2n_mul_bitstream.sv` at its production instantiation
`WIDTH = 128`, `BYTE_BITS = 8`:

* the **A operand load**, RTL `shift_in_byte`, driven by `a_valid` beats;
* the **destructive result shift-out**, RTL `accumulator <= accumulator >> 8`
  with `result_byte = accumulator[7:0]`, driven by `result_shift` beats.

`GF8.lean` and `formal/gf8_mul_formal.sv` cover the GF(2^8) product but tie
`a_last` high and `result_shift` low, so neither exercises byte ordering at
all. This file states and proves the ordering and round-trip facts that the
serial protocol depends on, at the real 128-bit width.

Every proof here is by structural induction plus bit-index arithmetic. None
uses `native_decide`, and none introduces a new trust assumption: the public
results depend only on `propext` and `Quot.sound`, which
`results/` records via `#print axioms`.

## What this does not establish

These are theorems about this Lean model, not about the SystemVerilog. The
corresponding RTL-level statement is checked separately and exhaustively by
`formal/gf128_serialize.sby` over the exact shipped modules. Nothing here
proves GF(2^128) multiplication, controller behaviour, or ISA conformance;
see `docs/PROOF_BOUNDARIES.md`.
-/

namespace LeanVMBMinCore.ByteSerialization

abbrev Byte := BitVec 8
abbrev Word := BitVec 128

/-- Beats in one 128-bit transfer at an 8-bit lane width. -/
def beats : Nat := 16

/-- Byte lane `i` of a 128-bit register, least-significant lane first.
This is the polynomial-basis byte order the RTL header specifies. -/
def byteAt (w : Word) (i : Nat) : Byte := (w >>> (8 * i)).setWidth 8

/-- RTL `shift_in_byte`: the register moves down one lane and the arriving
byte is written into the top lane. -/
def shiftInByte (w : Word) (b : Byte) : Word :=
  (w >>> 8) ||| (b.setWidth 128 <<< 120)

/-- RTL `a_shift` after a run of `a_valid` beats, bytes in arrival order. -/
def loadBytes (w : Word) : List Byte → Word
  | [] => w
  | b :: bs => loadBytes (shiftInByte w b) bs

/-- RTL `accumulator <= accumulator >> BYTE_BITS` on one `result_shift` beat. -/
def shiftOutByte (w : Word) : Word := w >>> 8

/-- The bytes presented on `result_byte` by `n` consecutive `result_shift`
beats. -/
def emitBytes : Nat → Word → List Byte
  | 0, _ => []
  | n + 1, w => byteAt w 0 :: emitBytes n (shiftOutByte w)

/-- Serialize a 128-bit value into its 16 wire bytes. -/
def serialize (w : Word) : List Byte := emitBytes beats w

/-- Deserialize 16 wire bytes into a 128-bit value, through the RTL's own
load path. The initial register contents are irrelevant; see
`loadBytes_length_eq_beats_independent`. -/
def deserialize (bs : List Byte) : Word := loadBytes 0 bs

/-! ## Single-beat lane lemmas -/

/-- A shift-out beat renames lane `i + 1` to lane `i`. -/
theorem byteAt_shiftOutByte (w : Word) (i : Nat) :
    byteAt (shiftOutByte w) i = byteAt w (i + 1) := by
  have h : 8 + 8 * i = 8 * (i + 1) := by omega
  simp [byteAt, shiftOutByte, ← BitVec.shiftRight_add, h]

/-- A load beat writes the arriving byte into the top lane. -/
theorem byteAt_shiftInByte_top (w : Word) (b : Byte) :
    byteAt (shiftInByte w b) 15 = b := by
  apply BitVec.eq_of_getLsbD_eq
  intro i hi
  simp only [byteAt, shiftInByte, BitVec.getLsbD_setWidth, BitVec.getLsbD_ushiftRight,
    BitVec.getLsbD_or, BitVec.getLsbD_shiftLeft]
  have e1 : 8 + (8 * 15 + (i : Nat)) = 128 + (i : Nat) := by omega
  have e2 : (8 * 15 + (i : Nat)) - 120 = (i : Nat) := by omega
  have e3 : ¬(8 * 15 + (i : Nat) < 120) := by omega
  have e4 : 8 * 15 + (i : Nat) < 128 := by omega
  rw [e1, e2]
  simp only [e3, e4, hi, BitVec.getLsbD_of_ge w (128 + (i : Nat)) (by omega)]
  simp [hi]
  omega

/-- A load beat renames every other lane `i + 1` to lane `i`. -/
theorem byteAt_shiftInByte_lt (w : Word) (b : Byte) (i : Nat) (h : i < 15) :
    byteAt (shiftInByte w b) i = byteAt w (i + 1) := by
  apply BitVec.eq_of_getLsbD_eq
  intro j hj
  simp only [byteAt, shiftInByte, BitVec.getLsbD_setWidth, BitVec.getLsbD_ushiftRight,
    BitVec.getLsbD_or, BitVec.getLsbD_shiftLeft]
  have e2 : 8 * i + (j : Nat) < 120 := by omega
  rw [show 8 + (8 * i + (j : Nat)) = 8 * (i + 1) + (j : Nat) by omega]
  simp [e2, hj]

/-- Two 128-bit values agreeing on all 16 byte lanes are equal. -/
theorem eq_of_byteAt_eq {x y : Word} (h : ∀ i, i < beats → byteAt x i = byteAt y i) :
    x = y := by
  apply BitVec.eq_of_getLsbD_eq
  intro k hk
  have hi : (k : Nat) / 8 < beats := by simp [beats]; omega
  have hb := congrArg (fun b => BitVec.getLsbD b ((k : Nat) % 8)) (h ((k : Nat) / 8) hi)
  simp only [byteAt, BitVec.getLsbD_setWidth, BitVec.getLsbD_ushiftRight] at hb
  have e : 8 * ((k : Nat) / 8) + (k : Nat) % 8 = (k : Nat) := by omega
  rw [e] at hb
  simpa [Nat.mod_lt] using hb

/-! ## Shift-out ordering -/

@[simp] theorem emitBytes_length (n : Nat) (w : Word) : (emitBytes n w).length = n := by
  induction n generalizing w with
  | zero => rfl
  | succ n ih => simp [emitBytes, ih]

/-- **Result shift-out ordering.** Beat `i` of the destructive serialization
presents byte lane `i`, that is, the least-significant byte leaves first. -/
theorem getElem_emitBytes (n : Nat) (w : Word) (i : Nat) (h : i < (emitBytes n w).length) :
    (emitBytes n w)[i] = byteAt w i := by
  induction n generalizing w i with
  | zero => simp [emitBytes] at h
  | succ n ih =>
      cases i with
      | zero => simp [emitBytes]
      | succ j =>
          have hj : j < (emitBytes n (shiftOutByte w)).length := by
            simpa [emitBytes] using h
          simpa [emitBytes, byteAt_shiftOutByte] using ih (shiftOutByte w) j hj

/-! ## Load ordering -/

/-- Lanes that predate a load run are pushed down by exactly the run length. -/
theorem byteAt_loadBytes_of_lt (bs : List Byte) (w : Word) (i : Nat)
    (h : i + bs.length < beats) :
    byteAt (loadBytes w bs) i = byteAt w (i + bs.length) := by
  induction bs generalizing w i with
  | nil => simp [loadBytes]
  | cons b bs ih =>
      have hlt : i + bs.length < 15 := by simp [beats] at h; omega
      have hrec : i + bs.length < beats := by simp [beats]; omega
      rw [loadBytes, ih (shiftInByte w b) i hrec,
        byteAt_shiftInByte_lt w b (i + bs.length) hlt]
      congr 1

/-- **A operand load ordering.** After a run of `bs.length ≤ 16` load beats,
lane `16 - bs.length + i` holds the `i`-th byte that arrived. -/
theorem byteAt_loadBytes (bs : List Byte) (w : Word) (hb : bs.length ≤ beats)
    (i : Nat) (hi : i < bs.length) :
    byteAt (loadBytes w bs) (beats - bs.length + i) = bs[i] := by
  induction bs generalizing w i with
  | nil => simp at hi
  | cons b bs ih =>
      cases i with
      | zero =>
          have hm : bs.length ≤ 15 := by simp [beats] at hb; omega
          have hlen : beats - (b :: bs).length + 0 + bs.length < beats := by
            simp [beats, List.length_cons]; omega
          rw [loadBytes,
            byteAt_loadBytes_of_lt bs (shiftInByte w b) (beats - (b :: bs).length + 0) hlen]
          rw [show beats - (b :: bs).length + 0 + bs.length = 15 by
            simp [beats, List.length_cons]; omega]
          simp [byteAt_shiftInByte_top]
      | succ j =>
          have hb' : bs.length ≤ beats := by simp [beats, List.length_cons] at hb ⊢; omega
          have hj : j < bs.length := by simp [List.length_cons] at hi; omega
          have hidx : beats - (b :: bs).length + (j + 1) = beats - bs.length + j := by
            simp [beats, List.length_cons] at hb ⊢; omega
          rw [loadBytes, hidx, ih (shiftInByte w b) hb' j hj]
          simp

/-- The 16-beat load overwrites the register completely: lane `i` holds the
`i`-th arriving byte, independently of the previous contents. -/
theorem byteAt_loadBytes_beats (bs : List Byte) (w : Word) (h : bs.length = beats)
    (i : Nat) (hi : i < beats) :
    byteAt (loadBytes w bs) i = bs[i]'(by omega) := by
  have := byteAt_loadBytes bs w (by omega) i (by omega)
  simpa [h] using this

/-- A full 16-beat load does not depend on the register's previous contents,
so back-to-back operands need no clearing beat between them. -/
theorem loadBytes_length_eq_beats_independent (bs : List Byte) (v w : Word)
    (h : bs.length = beats) : loadBytes v bs = loadBytes w bs := by
  apply eq_of_byteAt_eq
  intro i hi
  rw [byteAt_loadBytes_beats bs v h i hi, byteAt_loadBytes_beats bs w h i hi]

/-! ## Round trip -/

/-- **Deserialize then serialize.** Loading 16 bytes and shifting them back
out reproduces the wire byte sequence exactly, in order. -/
theorem serialize_loadBytes (bs : List Byte) (w : Word) (h : bs.length = beats) :
    serialize (loadBytes w bs) = bs := by
  apply List.ext_getElem
  · simp [serialize, h]
  · intro i h1 h2
    have hi : i < beats := by simpa [serialize] using h1
    simp only [serialize]
    rw [getElem_emitBytes beats (loadBytes w bs) i (by simpa using hi),
      byteAt_loadBytes_beats bs w h i hi]

/-- **Serialize then deserialize.** Shifting a 128-bit value out and loading
the resulting bytes back in reproduces the value exactly. -/
theorem loadBytes_serialize (w v : Word) : loadBytes v (serialize w) = w := by
  apply eq_of_byteAt_eq
  intro i hi
  have hlen : (serialize w).length = beats := by simp [serialize]
  rw [byteAt_loadBytes_beats (serialize w) v hlen i hi]
  exact getElem_emitBytes beats w i (by simpa using hi)

/-- Round trip through the named wire-level operations. -/
theorem deserialize_serialize (w : Word) : deserialize (serialize w) = w :=
  loadBytes_serialize w 0

/-- Round trip in the other direction, for any 16-byte wire sequence. -/
theorem serialize_deserialize (bs : List Byte) (h : bs.length = beats) :
    serialize (deserialize bs) = bs :=
  serialize_loadBytes bs 0 h

/-! ## Concrete orientation witnesses

The round-trip theorems above hold for either endianness, so they are pinned
here to the little-endian order the RTL header specifies. These are kernel
evaluations of the model on one concrete value; they would fail immediately
if the model were byte-reversed. -/

/-- The least-significant byte is emitted first. -/
example :
    serialize 0x0f0e0d0c0b0a09080706050403020100#128 =
      [0x00#8, 0x01#8, 0x02#8, 0x03#8, 0x04#8, 0x05#8, 0x06#8, 0x07#8,
       0x08#8, 0x09#8, 0x0a#8, 0x0b#8, 0x0c#8, 0x0d#8, 0x0e#8, 0x0f#8] := by
  rfl

/-- The first byte to arrive lands in the least-significant lane. -/
example :
    deserialize
        [0x00#8, 0x01#8, 0x02#8, 0x03#8, 0x04#8, 0x05#8, 0x06#8, 0x07#8,
         0x08#8, 0x09#8, 0x0a#8, 0x0b#8, 0x0c#8, 0x0d#8, 0x0e#8, 0x0f#8] =
      0x0f0e0d0c0b0a09080706050403020100#128 := by
  rfl

end LeanVMBMinCore.ByteSerialization
