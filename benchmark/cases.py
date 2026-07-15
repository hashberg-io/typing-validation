# SPDX-License-Identifier: LGPL-3.0-or-later

"""
What is measured, and against what.

Each case names a type, a value that is valid for it, a value that is not, and
how many type-nodes a single validation visits. That last number is what makes
figures comparable across shapes, and is the thing v1's ``ns/B`` was groping
toward.
"""

import random
from dataclasses import dataclass
from typing import Any, Callable, Literal, NamedTuple, TypedDict, final

SEED = 20260715
"""
Fixed, so that every run measures the same data.

v1 seeded from ``int(time())``, so no two runs measured the same values and no
run could be re-examined.
"""


class Point(NamedTuple):
    x: int
    y: int


class Movie(TypedDict):
    title: str
    year: int


type JSON = int | str | bool | None | list[JSON] | dict[str, JSON]


@final
@dataclass(frozen=True, slots=True)
class Case:
    """One thing to measure."""

    name: str
    """What to call it in the report."""

    t: Any
    """The type to validate against."""

    valid: Any
    """A value that is valid for it."""

    invalid: Any
    """A value that is not, so the failure path is measured too."""

    nodes: int
    """
    How many type-nodes one validation of :attr:`valid` visits.

    Work is proportional to this, not to the bytes the value occupies. Validating
    any ``int`` against ``int`` is exactly one ``isinstance`` call, while
    ``sys.getsizeof`` of an integer ranges from 28 to 72 bytes with its
    magnitude — so v1's ``ns/B`` moved 2.6x while the work stayed constant, and
    its figures across types could not be compared to each other at all.
    """

    baseline: Callable[[Any], bool] | None = None
    """
    A validator for this exact type, written by hand.

    The important baseline, because the compiled path's claim is precise and
    therefore falsifiable: *code as if you wrote it yourself, modulo a single
    function call*. That claim should be tested rather than admired.
    """

    v1_comparable: bool = True
    """
    Whether v1 supports this type, so the comparison means something.

    ``validate`` must not be slower than v1. It is the function everybody calls
    and most people will only ever call, so if the redesign buys two new
    mechanisms at the cost of the common path, it has failed regardless of what
    the other two achieve.
    """


def _rng() -> random.Random:
    return random.Random(SEED)


def _ints(n: int) -> list[int]:
    rng = _rng()
    return [rng.randint(-1000, 1000) for _ in range(n)]


def _strs(n: int) -> list[str]:
    rng = _rng()
    return [f"s{rng.randint(0, 1000)}" for _ in range(n)]


def _nested(depth: int) -> Any:
    val: Any = 1
    for _ in range(depth):
        val = [val]
    return val


def _hand_list_int(val: Any) -> bool:
    if not isinstance(val, list):
        return False
    for item in val:
        if not isinstance(item, int):
            return False
    return True


def _hand_dict_str_int(val: Any) -> bool:
    if not isinstance(val, dict):
        return False
    for key, item in val.items():
        if not isinstance(key, str) or not isinstance(item, int):
            return False
    return True


def _hand_optional_int(val: Any) -> bool:
    return isinstance(val, (int, type(None)))


def _hand_tuple_int_str(val: Any) -> bool:
    return (
        isinstance(val, tuple)
        and len(val) == 2
        and isinstance(val[0], int)
        and isinstance(val[1], str)
    )


def cases() -> list[Case]:
    """The corpus, covering the shapes that exercise different machinery."""
    return [
        # Scalars: where per-call overhead is the entire cost.
        Case("int", int, 12, "a", 1, lambda v: isinstance(v, int)),
        Case("str", str, "hi", 12, 1, lambda v: isinstance(v, str)),
        # Flat collections.
        Case(
            "list[int] x20",
            list[int],
            _ints(20),
            _ints(19) + ["a"],
            21,
            _hand_list_int,
        ),
        Case(
            "list[int] x1000",
            list[int],
            _ints(1000),
            _ints(999) + ["a"],
            1001,
            _hand_list_int,
        ),
        Case("list[str] x20", list[str], _strs(20), _strs(19) + [1], 21),
        Case("set[int] x20", set[int], set(_ints(20)), {*_ints(19), "a"}, 21),
        # Deeply nested: what the work stack exists for.
        Case(
            "nested list x100",
            _nested_type(100),
            _nested(100),
            _nested(99),
            101,
        ),
        # Mappings.
        Case(
            "dict[str, int] x20",
            dict[str, int],
            dict(zip(_strs(20), _ints(20))),
            dict(zip(_strs(19), _ints(19))) | {"x": "a"},
            41,
            _hand_dict_str_int,
        ),
        # Tuples.
        Case(
            "tuple[int, str]",
            tuple[int, str],
            (1, "a"),
            (1, 2),
            3,
            _hand_tuple_int_str,
        ),
        Case(
            "tuple[int, ...] x20",
            tuple[int, ...],
            tuple(_ints(20)),
            (*_ints(19), "a"),
            21,
        ),
        # Unions: the two paths are different machinery and must not be averaged
        # together. The first collapses to one isinstance against a tuple; the
        # second needs sequential attempts.
        Case("int | None (plain)", int | None, 12, "a", 1, _hand_optional_int),
        Case("int | str | None (plain)", int | str | None, 12, 1.0, 1),
        Case(
            "list[int] | list[str] (structured)",
            list[int] | list[str],
            _ints(20),
            _ints(19) + [1.0],
            22,
        ),
        # Literals.
        Case("Literal[1, 2, 3]", Literal[1, 2, 3], 2, 4, 1),
        # Annotation-derived forms, which pay resolution costs.
        Case(
            "TypedDict",
            Movie,
            {"title": "Jaws", "year": 1975},
            {"title": "Jaws"},
            3,
        ),
        # A named tuple can be built with the wrong field types, which is why
        # validating the fields is worth doing at all.
        Case(
            "NamedTuple",
            Point,
            Point(1, 2),
            Point("a", 2),  # type: ignore[arg-type]
            3,
        ),
        # Recursive aliases, where the compiled path must stop unrolling.
        Case(
            "recursive alias (JSON)",
            JSON,
            {"a": [1, "b", None]},
            {"a": [1.5]},
            9,
        ),
    ]


def _nested_type(depth: int) -> Any:
    t: Any = int
    for _ in range(depth):
        t = list[t]
    return t
