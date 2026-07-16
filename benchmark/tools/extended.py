# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The extended corpus: type *features*, and the combinations real code produces.

:mod:`benchmark.tools.cases` is the corpus the mechanisms are measured on and the
one the regression check reads, and it is deliberately left alone: it is a
baseline, and a baseline that grows is not one. This module adds to it rather
than editing it, and the report keeps the two apart to the end.

**The organising idea is a feature axis, not a type list.** The shapes that
stress different machinery are:

``scalar``
    One ``isinstance``. Per-call overhead is the entire cost.
``collection``
    Flat, homogeneous, iterated.
``nested``
    Structure within structure, non-trivially — the work stack's reason to exist.
``structured``
    Named fields with heterogeneous types: ``TypedDict``, ``NamedTuple``.
``union``
    Alternatives, which split into two quite different machineries.
``recursive``
    A cycle closed through an alias, where unrolling must stop.
``generic``
    A user's own parametrised class, reached through the extension protocol.
``numpy``
    A plugin, and therefore a de-optimisation boundary.

Taken individually those are eight cases. Taken in *all* combinations they would
be 127, and most would be uninhabitable (a scalar cannot also be recursive) or
degenerate. What is measured here instead is every feature alone, then the pairs
and triples that are both well-formed and *actually written by people*:
``list[dict[str, NDArray]]`` is a real shape, ``Literal`` inside a NumPy dtype is
not.

Two facts from ``knowledge/TYPES.md`` shape the generic cases and are worth
stating loudly, because they are easy to benchmark wrongly:

- A generic class validates on **its origin alone**. ``validate(Box("hi"),
  Box[int])`` is ``True``, by design — the class does not expose its arguments
  at runtime. So ``Box`` appears here twice: once bare, where the *correct*
  behaviour is to accept a value other libraries reject, and once with
  ``__validate__``, where the argument is checked. Only the second can have an
  invalid value that fails for the reason the case is named after.
- NumPy is a plugin and must be imported explicitly, so its cases are gated.
"""

from typing import (
    Any,
    Literal,
    NamedTuple,
    Protocol,
    TypedDict,
    runtime_checkable,
)

from typing_validation import is_valid

from .cases import Case

__all__ = ("extended_cases",)


# --------------------------------------------------------------------------
# Structured leaves, shared by the combination cases below.
# --------------------------------------------------------------------------


class Point(NamedTuple):
    x: int
    y: int


class Record(TypedDict):
    name: str
    count: int


class Config(TypedDict):
    """A structured type with a union field, so `structured+union` is a real cell."""

    mode: Literal["fast", "slow"]
    retries: int | None
    tags: list[str]


@runtime_checkable
class Sized(Protocol):
    def __len__(self) -> int: ...


# --------------------------------------------------------------------------
# Generic classes: the extension protocol, and its absence.
# --------------------------------------------------------------------------


class Box[T]:
    """
    A generic that does *not* declare `__validate__`.

    Its type argument is unchecked by design, so `Box[int]` accepts a `Box("hi")`.
    That is not a gap in the benchmark, it is the documented semantics, and the
    case exists to measure what origin-only dispatch costs — and to show peers
    disagreeing with a *correct* permissive answer.
    """

    __slots__ = ("item",)

    def __init__(self, item: T) -> None:
        self.item = item


class Checked[T]:
    """A generic that declares how its argument is validated."""

    __slots__ = ("item",)

    def __init__(self, item: T) -> None:
        self.item = item

    @classmethod
    def __validate__(cls, val: Any, args: tuple[Any, ...]) -> bool:
        return bool(is_valid(val.item, args[0]))


class Pair[K, V]:
    """Two type arguments, so arity is exercised rather than assumed."""

    __slots__ = ("key", "value")

    def __init__(self, key: K, value: V) -> None:
        self.key = key
        self.value = value

    @classmethod
    def __validate__(cls, val: Any, args: tuple[Any, ...]) -> bool:
        return bool(is_valid(val.key, args[0])) and bool(
            is_valid(val.value, args[1])
        )


# --------------------------------------------------------------------------
# Recursive aliases. The JSON alias in `cases.py` is the flat one; these close
# the cycle through different shapes.
# --------------------------------------------------------------------------

type Tree = dict[str, Tree | int]
"""
Recursion through a mapping: a cycle that closes on the value side.

The self-reference is *unquoted*. A PEP 695 alias is lazily evaluated and
resolves against its defining module, so quoting it would make it an inline
forward reference — which records no module and no owner, and is unsupported.
"""

type Nested = list[dict[str, tuple[int, ...]]]
"""Non-trivially nested, non-recursive: three container kinds, one inside the next."""

type Deep = dict[str, list[dict[str, list[int]]]]
"""Alternating mapping and sequence, four levels."""


def _tree(depth: int, breadth: int) -> Any:
    if depth == 0:
        return {f"k{i}": i for i in range(breadth)}
    return {f"k{i}": _tree(depth - 1, breadth) for i in range(breadth)}


def _tree_bad(depth: int, breadth: int) -> Any:
    val = _tree(depth, breadth)
    node = val
    for _ in range(depth):
        node = node["k0"]
    node["k0"] = 1.5  # a float: not `Tree | int`, at the deepest point
    return val


# --------------------------------------------------------------------------
# Hand-written baselines, for the cases where the compiled path makes a claim.
# --------------------------------------------------------------------------


def _hand_point(val: Any) -> bool:
    return (
        isinstance(val, Point)
        and isinstance(val[0], int)
        and isinstance(val[1], int)
    )


def _hand_list_dict_str_point(val: Any) -> bool:
    if not isinstance(val, list):
        return False
    for d in val:
        if not isinstance(d, dict):
            return False
        for k, v in d.items():
            if not isinstance(k, str) or not _hand_point(v):
                return False
    return True


def _hand_nested(val: Any) -> bool:
    if not isinstance(val, list):
        return False
    for d in val:
        if not isinstance(d, dict):
            return False
        for k, t in d.items():
            if not isinstance(k, str) or not isinstance(t, tuple):
                return False
            for i in t:
                if not isinstance(i, int):
                    return False
    return True


def _hand_union_scalar(val: Any) -> bool:
    return isinstance(val, (int, str, float, type(None)))


# --------------------------------------------------------------------------
# Values.
# --------------------------------------------------------------------------


def _points(n: int) -> list[Point]:
    return [Point(i, i + 1) for i in range(n)]


def _records(n: int) -> list[Record]:
    return [{"name": f"n{i}", "count": i} for i in range(n)]


def _nested_val(n: int) -> list[dict[str, tuple[int, ...]]]:
    return [{f"k{j}": (j, j + 1, j + 2) for j in range(3)} for _ in range(n)]


def _deep_val() -> dict[str, list[dict[str, list[int]]]]:
    return {
        f"a{i}": [{f"b{j}": [j, j + 1] for j in range(3)} for _ in range(3)]
        for i in range(3)
    }


def _numpy_cases() -> list[Case]:
    """
    NumPy, alone and in combination.

    The plugin is a de-optimisation boundary: the compiler has no source for its
    check and can only emit a call into it. What that costs *inside* a structure
    — a list of arrays, a mapping of arrays — is not measurable from the plain
    `NDArray` cases in `cases.py`, and is the reason these exist.

    The structured case uses `dict[str, NDArray]` rather than a `TypedDict`
    naming `NDArray`. A `TypedDict` would have to be declared inside this
    function, because its annotation is only importable when the optional
    dependency is present — and a class nested in a function is a shape this
    package does not otherwise contain, and which `test_style` does not exempt
    from its no-blank-lines rule. The cell being measured is a plugin check
    reached through a mapping, which this expresses exactly.
    """
    try:
        import numpy as np
        import typing_validation.numpy  # noqa: F401
        from numpy.typing import NDArray
    except ImportError:  # pragma: no cover
        return []
    arrs = [np.arange(10, dtype=np.uint8) for _ in range(20)]
    bad_arrs = [np.arange(10, dtype=np.uint8) for _ in range(19)] + [
        np.arange(10, dtype=np.float32)
    ]
    frame: Any = {"data": np.zeros(10, dtype=np.float64)}
    bad_frame: Any = {"data": np.zeros(10, dtype=np.uint8)}
    return [
        Case(
            "numpy+collection: list[NDArray[uint8]] x20",
            list[NDArray[np.uint8]],
            arrs,
            bad_arrs,
            41,
            v1_comparable=False,
            extension="numpy",
        ),
        Case(
            "numpy+union: NDArray[u8] | NDArray[f4]",
            NDArray[np.uint8] | NDArray[np.float32],
            np.arange(10, dtype=np.float32),
            np.arange(10, dtype=np.int64),
            3,
            v1_comparable=False,
            extension="numpy",
        ),
        Case(
            "numpy+structured: dict[str, NDArray[f8]]",
            dict[str, NDArray[np.float64]],
            frame,
            bad_frame,
            4,
            v1_comparable=False,
            extension="numpy",
        ),
        Case(
            "numpy+generic: Checked[NDArray[uint8]]",
            Checked[NDArray[np.uint8]],
            Checked(np.arange(10, dtype=np.uint8)),
            Checked(np.arange(10, dtype=np.float32)),
            3,
            v1_comparable=False,
            extension="numpy",
        ),
        Case(
            "numpy+nested: dict[str, list[NDArray[u8]]]",
            dict[str, list[NDArray[np.uint8]]],
            {f"k{i}": arrs[:5] for i in range(4)},
            {f"k{i}": (arrs[:5] if i else bad_arrs[-5:]) for i in range(4)},
            4 + 4 * (1 + 5 * 2),
            v1_comparable=False,
            extension="numpy",
        ),
    ]


def extended_cases() -> list[Case]:
    """The feature axes, then the combinations that are inhabitable and real."""
    return _single_feature() + _combinations() + _numpy_cases()


def _single_feature() -> list[Case]:
    """Each axis alone, so a combination's cost can be attributed."""
    return [
        # -- scalar ---------------------------------------------------------
        Case(
            "scalar: float",
            float,
            1.5,
            "a",
            1,
            lambda v: isinstance(v, float),
        ),
        Case(
            "scalar: bool (int subclass)",
            bool,
            True,
            1,
            1,
            lambda v: isinstance(v, bool),
        ),
        # -- collection -----------------------------------------------------
        Case(
            "collection: frozenset[int] x20",
            frozenset[int],
            frozenset(range(20)),
            frozenset(range(19)) | {"a"},
            21,
        ),
        # -- structured -----------------------------------------------------
        Case(
            "structured: TypedDict with union field",
            Config,
            {"mode": "fast", "retries": None, "tags": ["a", "b"]},
            {"mode": "medium", "retries": None, "tags": ["a"]},
            6,
        ),
        # -- union ----------------------------------------------------------
        Case(
            "union: 4-way scalar",
            int | str | float | None,
            1.5,
            [],
            1,
            _hand_union_scalar,
        ),
        # -- recursive ------------------------------------------------------
        Case(
            "recursive: Tree (mapping cycle) d3xb3",
            Tree,
            _tree(3, 3),
            _tree_bad(3, 3),
            121,
        ),
        # -- generic --------------------------------------------------------
        Case(
            "generic: Box[int] (origin-only)",
            Box[int],
            Box(1),
            # NOT a failing value for this type: a bare generic is checked on
            # its origin alone, so this is `True` by design. The `invalid` slot
            # is a value that genuinely fails — a non-Box — and the interesting
            # column is the peers' disagreement on `Box("hi")`, itemised in the
            # report rather than smuggled in here.
            42,
            1,
        ),
        Case(
            "generic: Checked[int] (__validate__)",
            Checked[int],
            Checked(1),
            Checked("a"),
            2,
            extension="__validate__",
        ),
        Case(
            "generic: Pair[str, int] (two args)",
            Pair[str, int],
            Pair("a", 1),
            Pair("a", "b"),
            3,
            extension="__validate__",
        ),
        # -- protocol -------------------------------------------------------
        Case(
            "protocol: runtime_checkable Sized",
            Sized,
            [1, 2, 3],
            5,
            1,
        ),
    ]


def _combinations() -> list[Case]:
    """
    Pairs and triples that are inhabitable and that real code produces.

    Each name says which axes it crosses, so a slow figure can be attributed to
    a feature rather than to a shape nobody can reason about.
    """
    return [
        # -- nested (the axis alone, non-trivially) -------------------------
        Case(
            "nested: list[dict[str, tuple[int,...]]] x20",
            Nested,
            _nested_val(20),
            _nested_val(19) + [{"k0": (1, "a")}],
            20 * 10 + 1,
            _hand_nested,
        ),
        Case(
            "nested: dict[str,list[dict[str,list[int]]]]",
            Deep,
            _deep_val(),
            {"a0": [{"b0": [1.5]}]},
            3 * (1 + 3 * (1 + 3 * 3)) + 1,
        ),
        # -- collection+structured -----------------------------------------
        Case(
            "collection+structured: list[NamedTuple] x20",
            list[Point],
            _points(20),
            _points(19) + [Point("a", 1)],  # type: ignore[arg-type]
            61,
        ),
        Case(
            "collection+structured: list[TypedDict] x20",
            list[Record],
            _records(20),
            _records(19) + [{"name": "x", "count": "no"}],
            61,
        ),
        # -- nested+structured ----------------------------------------------
        Case(
            "nested+structured: list[dict[str, Point]] x10",
            list[dict[str, Point]],
            [{f"k{j}": Point(j, j) for j in range(3)} for _ in range(10)],
            [{f"k{j}": Point(j, j) for j in range(3)} for _ in range(9)]
            + [{"k0": Point("a", 1)}],  # type: ignore[arg-type]
            10 * (1 + 3 * 4) + 1,
            _hand_list_dict_str_point,
        ),
        # -- collection+union ------------------------------------------------
        Case(
            "collection+union: list[int|str] x20 (plain)",
            list[int | str],
            [i if i % 2 else str(i) for i in range(20)],
            [i if i % 2 else str(i) for i in range(19)] + [1.5],
            21,
        ),
        Case(
            "collection+union: list[list[int]|dict[str,int]] x20",
            list[list[int] | dict[str, int]],
            [[1, 2] if i % 2 else {"a": 1} for i in range(20)],
            [[1, 2] if i % 2 else {"a": 1} for i in range(19)] + [(1,)],
            20 * 4 + 1,
        ),
        # -- structured+union -------------------------------------------------
        Case(
            "structured+union: TypedDict | NamedTuple",
            Record | Point,
            Point(1, 2),
            {"name": "x"},
            4,
        ),
        # -- nested+union -----------------------------------------------------
        Case(
            "nested+union: list[dict[str, int|None]] x10",
            list[dict[str, int | None]],
            [
                {f"k{j}": (j if j % 2 else None) for j in range(3)}
                for _ in range(10)
            ],
            [
                {f"k{j}": (j if j % 2 else None) for j in range(3)}
                for _ in range(9)
            ]
            + [{"k0": 1.5}],
            10 * (1 + 3 * 2) + 1,
        ),
        # -- recursive+union ---------------------------------------------------
        Case(
            "recursive+union: Tree | list[Tree]",
            Tree | list[Tree],
            [_tree(2, 3), _tree(2, 3)],
            [_tree(2, 3), 1.5],
            80,
        ),
        # -- generic+X ----------------------------------------------------------
        Case(
            "generic+collection: Checked[list[int]] x20",
            Checked[list[int]],
            Checked(list(range(20))),
            Checked(list(range(19)) + ["a"]),
            22,
            extension="__validate__",
        ),
        Case(
            "generic+union: Checked[int|str]",
            Checked[int | str],
            Checked("a"),
            Checked(1.5),
            2,
            extension="__validate__",
        ),
        Case(
            "generic+structured: Checked[TypedDict]",
            Checked[Record],
            Checked({"name": "a", "count": 1}),
            Checked({"name": "a", "count": "b"}),
            4,
            extension="__validate__",
        ),
        Case(
            "generic+generic: Checked[Checked[int]]",
            Checked[Checked[int]],
            Checked(Checked(1)),
            Checked(Checked("a")),
            3,
            extension="__validate__",
        ),
        Case(
            "generic+recursive: Checked[Tree]",
            Checked[Tree],
            Checked(_tree(2, 3)),
            Checked(_tree_bad(2, 3)),
            41,
            extension="__validate__",
        ),
        Case(
            "generic+nested: Pair[str, list[dict[str,int]]]",
            Pair[str, list[dict[str, int]]],
            Pair("k", [{"a": 1}, {"b": 2}]),
            Pair("k", [{"a": 1}, {"b": "c"}]),
            10,
            extension="__validate__",
        ),
        # -- triples -------------------------------------------------------------
        Case(
            "nested+structured+union: list[dict[str, Point|Record]] x10",
            list[dict[str, Point | Record]],
            [
                {
                    f"k{j}": (
                        Point(j, j) if j % 2 else {"name": "n", "count": j}
                    )
                    for j in range(3)
                }
                for _ in range(10)
            ],
            [
                {
                    f"k{j}": (
                        Point(j, j) if j % 2 else {"name": "n", "count": j}
                    )
                    for j in range(3)
                }
                for _ in range(9)
            ]
            + [{"k0": 1.5}],
            10 * (1 + 3 * 5) + 1,
        ),
        Case(
            "collection+generic+structured: list[Checked[Record]] x10",
            list[Checked[Record]],
            [Checked({"name": f"n{i}", "count": i}) for i in range(10)],
            [Checked({"name": f"n{i}", "count": i}) for i in range(9)]
            + [Checked({"name": "x", "count": "no"})],
            10 * 4 + 1,
            extension="__validate__",
        ),
    ]
