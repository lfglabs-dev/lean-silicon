"""Host-owned VM state: memory, the written bitmap, pointers and witnesses.

None of this crosses the LSC-1 boundary.  The ASIC never fetches a cell, never
holds the written bitmap and never searches the pointer map; the host reads its
own state and hands each transaction every cell that transition can touch.
"""
from dataclasses import dataclass, field

from .errors import UnsupportedCapability, WriteOnceViolation
from .protocol import protocol

MASK = (1 << 128) - 1


def field_inverse(value: int) -> int:
    """Invert in GF(2^128) by raising to the power 2**128 - 2.

    The host proposes this witness; the endpoint accepts it only after checking
    ``known * proposed == 1`` (D-003), so a wrong witness cannot be laundered
    into a committed write.
    """
    if value == 0:
        raise ZeroDivisionError("zero has no inverse in GF(2**128)")
    # 2**128 - 2 has every exponent bit set except bit 0.
    result = 1
    square = value
    for bit in range(128):
        if bit:
            result = protocol.field_mul(result, square)
        square = protocol.field_mul(square, square)
    return result


class PointerMap:
    """Forward and reverse g-power tables, grown on demand.

    ``encode(i)`` is ``g**i``.  The reverse direction is the search the ASIC is
    explicitly not allowed to perform: the host looks the index up here and
    sends it as a witness, and the endpoint re-encodes it to check the pointer.
    """

    def __init__(self) -> None:
        self._forward = [1]
        self._reverse = {1: 0}

    def _grow(self, index: int) -> None:
        if index >= protocol.INDEX_LIMIT:
            raise UnsupportedCapability(
                f"index {index} is outside the LSC-1 v1 window of "
                f"2**{protocol.INDEX_BITS} cells"
            )
        while len(self._forward) <= index:
            value = protocol.field_xtime(self._forward[-1])
            self._reverse.setdefault(value, len(self._forward))
            self._forward.append(value)

    def encode(self, index: int) -> int:
        self._grow(index)
        return self._forward[index]

    def index_of(self, pointer: int) -> int:
        """Reverse a pointer to its index, growing the table until it appears."""
        if pointer in self._reverse:
            return self._reverse[pointer]
        self._grow(protocol.INDEX_LIMIT - 1)
        if pointer not in self._reverse:
            raise UnsupportedCapability(
                f"pointer {pointer:#034x} is not a g-power below "
                f"2**{protocol.INDEX_BITS}"
            )
        return self._reverse[pointer]


@dataclass
class HostMemory:
    """Write-once VM memory plus the bookkeeping the ASIC delegates upward."""

    cells: dict[int, int] = field(default_factory=dict)
    access_counts: dict[int, int] = field(default_factory=dict)
    deferred: list[tuple[int, int]] = field(default_factory=list)
    pointers: PointerMap = field(default_factory=PointerMap)

    @classmethod
    def with_public_input(cls, first: int, second: int) -> "HostMemory":
        """Seed ``m[0]`` and ``m[1]``, matching the frozen public-input rule."""
        return cls(cells={0: first & MASK, 1: second & MASK})

    def written(self, address: int) -> bool:
        return address in self.cells

    def read(self, address: int) -> int | None:
        return self.cells.get(address)

    def cell(self, address: int) -> "protocol.Cell":
        """Package one cell for a request payload: present with a value, or absent."""
        value = self.cells.get(address)
        return protocol.ABSENT if value is None else protocol.Cell(True, value)

    def apply_write(self, address: int, value: int) -> None:
        existing = self.cells.get(address)
        if existing is not None and existing != value:
            raise WriteOnceViolation(
                f"cell {address} already holds {existing:#034x}, "
                f"endpoint returned {value:#034x}"
            )
        self.cells[address] = value & MASK

    def count_access(self, address: int) -> None:
        self.access_counts[address] = self.access_counts.get(address, 0) + 1

    def record_deferred(self, target: int, local: int) -> None:
        self.deferred.append((target, local))

    def resolve_deferred(self) -> list[tuple[int, int]]:
        """Close every deferred equality whose two cells are now both known.

        Returns the pairs that are still open.  A pair whose sides disagree is a
        host-detected inconsistency, not something the ASIC can see later.
        """
        pending = self.deferred
        while True:
            still_open: list[tuple[int, int]] = []
            resolved = 0
            for target, local in pending:
                left = self.cells.get(target)
                right = self.cells.get(local)
                if left is None and right is None:
                    still_open.append((target, local))
                elif left is None:
                    self.apply_write(target, right)
                    resolved += 1
                elif right is None:
                    self.apply_write(local, left)
                    resolved += 1
                elif left != right:
                    raise WriteOnceViolation(
                        f"deferred equality {target} == {local} is unsatisfiable: "
                        f"{left:#034x} != {right:#034x}"
                    )
            if resolved == 0:
                self.deferred = still_open
                return still_open
            pending = still_open

    def image(self, size: int) -> list[int]:
        """Dense prefix of the memory image, unwritten cells read as zero."""
        return [self.cells.get(address, 0) for address in range(size)]
