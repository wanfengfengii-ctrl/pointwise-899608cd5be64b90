from collections.abc import Callable
from typing import Generic, TypeVar


Reference = TypeVar('Reference')


class AvailableReferences(Generic[Reference]):
    """A pool whose caller admits reference instances in their original order."""

    def __init__(self) -> None:
        self._available: list[Reference] = []

    def admit(self, reference: Reference) -> None:
        self._available.append(reference)

    def take_earliest(self, eligible: Callable[[Reference], bool]) -> Reference | None:
        for index, reference in enumerate(self._available):
            if eligible(reference):
                return self._available.pop(index)
        return None
