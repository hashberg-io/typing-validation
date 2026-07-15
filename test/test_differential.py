# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Generated cases, checked for agreement between independent implementations.

The curated corpus proves the cases we thought of. This probes the ones we did
not, which matters because the whole architecture rests on independent
implementations of one specification agreeing, and **the drift is silent**: a
mechanism that disagrees returns a wrong answer with no exception and no symptom.

There is only one *validator* in 2.0, so there is not yet a mechanism axis to
cross. But there are already two independent walkers of value against type — the
interpreter, which dispatches on the raw type with no cache, and ``diagnose``,
which reads the node model — and they share no code. So the oracle exists
already: **whenever the interpreter rejects a value, diagnosis must reproduce
that failure, and whenever it accepts one, diagnosis must find nothing.**

``validator`` in 2.1 and ``compiled_validator`` in 2.2 join by being added to
``MECHANISMS``.
"""

import random
from typing import Any, Literal, NamedTuple, NotRequired, TypedDict

import pytest

from typing_validation import UnsupportedTypeError, ValidationError, is_valid
from typing_validation.diagnosis import DiagnosisFailure, _diagnose

SEED = 20260715


class Pt(NamedTuple):
    x: int
    y: str


class TD(TypedDict):
    a: int
    b: NotRequired[list[str]]


type Rec = int | str | list[Rec] | dict[str, Rec]

TYPES: list[Any] = [
    int,
    str,
    bool,
    float,
    bytes,
    None,
    list[int],
    list[str],
    list[list[int]],
    set[int],
    frozenset[str],
    dict[str, int],
    dict[str, list[int]],
    tuple[int, str],
    tuple[int, ...],
    tuple[()],
    int | None,
    int | str,
    list[int] | list[str],
    list[int] | str,
    dict[str, int] | list[int],
    list[list[int] | str],
    Literal[1, 2],
    Literal["a", None],
    Pt,
    TD,
    Rec,
    list[int | None],
    tuple[list[int], dict[str, int]],
]
"""
Types spanning every arm the interpreter has, weighted toward the ones with
non-trivial control flow: unions with structured members, and recursion.
"""


def _values(rng: random.Random) -> list[Any]:
    """A pool of values, most of which are invalid for most of the types."""
    leaves: list[Any] = [
        0,
        1,
        -1,
        True,
        False,
        None,
        1.5,
        "a",
        "",
        b"a",
        (),
        [],
        {},
        set(),
        Pt(1, "a"),
        Pt("a", 1),  # type: ignore[arg-type]
        {"a": 1},
        {"a": "b"},
        {1: 1},
    ]
    out = list(leaves)
    for _ in range(60):
        pick = rng.choice(leaves)
        out.append([pick])
        out.append([pick, rng.choice(leaves)])
        out.append((pick, rng.choice(leaves)))
        out.append({"k": pick})
        out.append({"a": [pick]})
    return out


def _cases() -> list[tuple[Any, Any]]:
    rng = random.Random(SEED)
    values = _values(rng)
    return [(val, t) for t in TYPES for val in values]


CASES = _cases()


@pytest.mark.parametrize("case", CASES, ids=lambda c: repr(c)[:60])
def test_diagnosis_agrees_with_the_interpreter(case: tuple[Any, Any]) -> None:
    """
    Two independent walkers, one specification.

    The interpreter dispatches on the raw type and caches nothing; diagnosis
    reads the interned node model. If they disagree, one has drifted from the
    catalogue — and this is the only thing that would say so.
    """
    val, t = case
    try:
        valid = is_valid(val, t)
    except UnsupportedTypeError:
        pytest.skip("unsupported type")
    failure = _diagnose(val, t)
    if valid:
        assert (
            failure is None
        ), "the interpreter accepted this value but diagnosis found a failure"
    else:
        assert failure is not None, (
            "the interpreter rejected this value but diagnosis could not "
            "reproduce it"
        )


@pytest.mark.parametrize("case", CASES, ids=lambda c: repr(c)[:60])
def test_validation_never_mutates_the_value(case: tuple[Any, Any]) -> None:
    """
    Purity deserves a real test rather than a convention.

    Three separate parts of the design assume it: union members are tried in
    sequence and a failed attempt must leave nothing behind, the mechanisms must
    agree on every input, and diagnosis re-walks the same value a second time.
    """
    val, t = case
    before = repr(val)
    try:
        is_valid(val, t)
    except UnsupportedTypeError:
        pytest.skip("unsupported type")
    assert repr(val) == before


@pytest.mark.parametrize("case", CASES, ids=lambda c: repr(c)[:60])
def test_no_stray_exception_ever_escapes(case: tuple[Any, Any]) -> None:
    """
    Only the library's own errors come out.

    A stray ``NameError`` from resolving an annotation, or a raw ``TypeError``
    from inside ``isinstance``, is neither a validation failure nor an honest
    error — and a raw ``TypeError`` is indistinguishable from a rejection to
    anyone catching one, which is how v1's ``NamedTuple`` crash passed its own
    test suite.
    """
    val, t = case
    try:
        is_valid(val, t)
    except ValidationError, UnsupportedTypeError, DiagnosisFailure:
        pass
