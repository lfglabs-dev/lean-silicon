/-!
Integer-index refinement for leanVM-b's g-power addresses.
-/

universe u

namespace LeanVMBMinCore

/--
The only algebraic fact needed to refine integer indices to architectural
addresses is that encoding index addition becomes field multiplication.
For leanVM-b, `encode i = g^i`.
-/
structure AddressEncoding (F : Type u) [Mul F] where
  encode : Nat → F
  encode_add : ∀ i j, encode (i + j) = encode i * encode j

namespace AddressEncoding

variable {F : Type u} [Mul F]

/-- Physical frame-relative addition implements architectural multiplication. -/
theorem frameRelative (E : AddressEncoding F) (fp offset : Nat) :
    E.encode (fp + offset) = E.encode fp * E.encode offset :=
  E.encode_add fp offset

/-- Incrementing an integer PC implements multiplication by the generator. -/
theorem nextPc (E : AddressEncoding F) (pc : Nat) :
    E.encode (pc + 1) = E.encode pc * E.encode 1 :=
  E.encode_add pc 1

/-- A resolved indirect pointer plus an offset has the specified field address. -/
theorem resolvedDeref (E : AddressEncoding F) (base beta : Nat) :
    E.encode (base + beta) = E.encode base * E.encode beta :=
  E.encode_add base beta

end AddressEncoding
end LeanVMBMinCore
