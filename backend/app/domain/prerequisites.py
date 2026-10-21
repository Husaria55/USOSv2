"""Wymagania wstępne."""
from collections.abc import Iterable, Mapping


def missing_prerequisites(required: Iterable[int], passed: Iterable[int]) -> set[int]:
    """Kursy wymagane, których student nie zaliczył (wystarczy jedno zaliczenie)."""
    return set(required) - set(passed)


def creates_cycle(graph: Mapping[int, Iterable[int]], course_id: int, required_id: int) -> bool:
    """Czy dodanie wymagania course_id -> required_id utworzy cykl.

    graph: kurs -> kursy, których wymaga. Cykl powstaje, gdy required_id
    (bezpośrednio albo pośrednio) wymaga już course_id.
    """
    if course_id == required_id:
        return True
    stack, seen = [required_id], set()
    while stack:
        c = stack.pop()
        if c == course_id:
            return True
        if c in seen:
            continue
        seen.add(c)
        stack.extend(graph.get(c, ()))
    return False
