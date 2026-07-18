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


class Wide(TypedDict):
    """
    A TypedDict wide enough that unrolling it is a decision rather than a
    detail.

    Forty fields is what the inlining budget is *for*: emitted inline, this is
    forty checks at every occurrence, and the design's own worked example of the
    body exploding.
    """

    f00: int
    f01: str
    f02: int
    f03: str
    f04: int
    f05: str
    f06: int
    f07: str
    f08: int
    f09: str
    f10: int
    f11: str
    f12: int
    f13: str
    f14: int
    f15: str
    f16: int
    f17: str
    f18: int
    f19: str
    f20: int
    f21: str
    f22: int
    f23: str
    f24: int
    f25: str
    f26: int
    f27: str
    f28: int
    f29: str
    f30: int
    f31: str
    f32: int
    f33: str
    f34: int
    f35: str
    f36: int
    f37: str
    f38: int
    f39: str


type Shared = dict[str, list[int]]
"""
One sub-type, mentioned many times over.

Sharing is what makes composition cheap and what unrolling destroys by
construction: a node referenced twenty times unrolls twenty times. Nothing else
in this corpus stresses that, so nothing else can tell the inlining budget it is
wrong.
"""

type SharedTwenty = tuple[
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
    Shared,
]


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

    needs: str | None = None
    """
    A module that must be importable for this case to mean anything.

    NumPy is optional, and a benchmark that silently skips is worse than one that
    says why.
    """

    extension: str | None = None
    """
    The extension of this library's own that the case exercises, if any.

    :obj:`None` for the type forms the whole field claims to support. Otherwise
    the name of a mechanism no peer implements --- ``"numpy"`` for the plugin,
    ``"__validate__"`` for the protocol that checks a generic's arguments.

    This exists because a peer's verdict on such a case says nothing about the
    peer. Scoring a library "wrong" for not implementing a protocol we invented,
    and then reporting the total as a correctness percentage, measures whether it
    is typing-validation. The capability is real and worth publishing; it is just
    not the same claim, so the report counts the two separately and never adds
    them up.
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


def _wide() -> dict[str, Any]:
    return {f"f{i:02}": (i if i % 2 == 0 else f"s{i}") for i in range(40)}


def _shared_one() -> dict[str, list[int]]:
    return {"a": _ints(5), "b": _ints(5)}


_WIDE_FIELDS = tuple(
    (f"f{i:02}", int if i % 2 == 0 else str) for i in range(40)
)
"""
The field table, built once.

Hoisted out of the check below because a competent programmer would hoist it: an
earlier version built the key with an f-string per field per call, which made the
baseline exactly as slow as the interpreter and would have flattered every
mechanism measured against it.
"""

_MISSING = object()


def _hand_wide(val: Any) -> bool:
    if not isinstance(val, dict):
        return False
    for key, field_t in _WIDE_FIELDS:
        item = val.get(key, _MISSING)
        if item is _MISSING or not isinstance(item, field_t):
            return False
    return True


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


def _numpy_cases() -> list[Case]:
    """
    NumPy, which is the only plugin and therefore the only measurement of what a
    plugin costs.

    A plugin is a **de-optimisation boundary**: the compiler has no source for
    its check and can only emit a call into it, so unrolling stops at its edge.
    That is unavoidable — you cannot inline code you do not have — and the size
    of it is a fact worth having rather than assuming.
    """
    try:
        import numpy as np
        import typing_validation.numpy  # noqa: F401
        from numpy.typing import NDArray
    except ImportError:  # pragma: no cover
        return []
    small = np.arange(20, dtype=np.uint8)
    big = np.arange(10_000, dtype=np.uint8)
    wrong = np.arange(20, dtype=np.float32)
    matrix = np.zeros((100, 100), dtype=np.uint8)
    return [
        # The array's size is irrelevant to the work: dtype and shape are checked
        # once, whatever the array holds. Two sizes, to say so out loud.
        Case(
            "NDArray[uint8] x20",
            NDArray[np.uint8],
            small,
            wrong,
            2,
            v1_comparable=False,
            extension="numpy",
        ),
        Case(
            "NDArray[uint8] x10000",
            NDArray[np.uint8],
            big,
            np.arange(10_000, dtype=np.float32),
            2,
            v1_comparable=False,
            extension="numpy",
        ),
        Case(
            "ndarray[(int, int), uint8]",
            np.ndarray[tuple[int, int], np.dtype[np.uint8]],
            matrix,
            small,
            3,
            v1_comparable=False,
            extension="numpy",
        ),
    ]


def cases() -> list[Case]:
    """The corpus, covering the shapes that exercise different machinery."""
    return _core_cases() + _numpy_cases()


def _core_cases() -> list[Case]:
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
        # Heavily shared sub-types: what the inlining budget trades against.
        # Unrolling destroys sharing by construction, so one sub-type mentioned
        # twenty times unrolls twenty times, and this is the only case that can
        # say whether that matters.
        Case(
            "shared subtype x20",
            SharedTwenty,
            tuple(_shared_one() for _ in range(20)),
            tuple(_shared_one() for _ in range(19)) + ({"a": ["x"]},),
            20 * 13 + 1,
        ),
        # Wide, where inlining is the design's own worked example of a body
        # exploding.
        Case(
            "TypedDict x40 fields",
            Wide,
            _wide(),
            _wide() | {"f39": 39},
            41,
            _hand_wide,
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
