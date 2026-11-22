# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The corpus of validation cases, and the mechanisms they are run through.

This module **owns** the cases. v1 put its case tables in ``test_00_validate.py``
and had ``test_01_can_validate.py`` do ``from .test_00_validate import ...``, so
one test file reached into another's privates and the file numbering was
load-bearing — it still has a hole where ``test_02`` used to be. A module that
owns the corpus makes the ordering irrelevant and the numbering unnecessary.

The corpus is organised **per type form, mirroring TYPES.md**, so that a change
to the catalogue has one obvious place to land.
"""

import collections
from abc import ABC
import collections.abc as abc
import enum
import importlib.util
import sys
import warnings
from typing import (
    Annotated,
    Any,
    Callable,
    Iterable,
    Iterator,
    Literal,
    NamedTuple,
    NewType,
    NotRequired,
    Optional,
    Protocol,
    ReadOnly,
    Required,
    Self,
    TypeVar,
    TypedDict,
    Union,
    runtime_checkable,
)

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from typing import ByteString

# --------------------------------------------------------------------------
# Fixtures referred to by the corpus below.
# --------------------------------------------------------------------------


class Colour(enum.Enum):
    RED = 1
    GREEN = 2


class Point(NamedTuple):
    x: int
    y: int


class Tagged(NamedTuple):
    name: str
    items: list[int]


class BadPoint(NamedTuple):
    x: int
    y: "NeverDefinedAnywhere"  # type: ignore[name-defined]


LegacyPoint = collections.namedtuple("LegacyPoint", ["x", "y"])


class Movie(TypedDict):
    title: str
    year: int


class PartialMovie(TypedDict):
    title: str
    year: NotRequired[int]


class QualifiedMovie(TypedDict):
    title: ReadOnly[str]
    year: Required[int]
    tags: NotRequired[ReadOnly[list[str]]]


class NestedMovie(TypedDict):
    title: str
    sequel: NotRequired["NestedMovie"]


class BadMovie(TypedDict):
    title: str
    other: "NeverDefinedAnywhere"  # type: ignore[name-defined]


@runtime_checkable
class Sized(Protocol):
    def __len__(self) -> int: ...


class NotRuntime(Protocol):
    def frobnicate(self) -> None: ...


@runtime_checkable
class HasX(Protocol):
    x: int


class Shape(ABC):
    pass


class Square(Shape):
    pass


class Box[T]:
    def __init__(self, item: T) -> None:
        self.item = item


class Plain:
    pass


class SubList(list[int]):
    pass


T = TypeVar("T")
TBound = TypeVar("TBound", bound=int)
TConstrained = TypeVar("TConstrained", int, str)

UserId = NewType("UserId", int)
Nested = NewType("Nested", UserId)

type MyInt = int
type Aliased = int | str
type JSON = int | str | bool | None | list[JSON] | dict[str, JSON]
type Pair[P] = tuple[P, P]


# --------------------------------------------------------------------------
# The corpus.
# --------------------------------------------------------------------------

VALID: list[tuple[Any, Any]] = []
"""Pairs ``(val, t)`` for which validation must succeed."""

INVALID: list[tuple[Any, Any]] = []
"""Pairs ``(val, t)`` for which validation must fail."""

UNSUPPORTED: list[tuple[Any, Any]] = []
"""
Pairs ``(val, t)`` for which validation must raise ``UnsupportedTypeError``.

The value matters, and is chosen to **reach** the unsupported component.
``validate`` walks the value and the type together and raises when it arrives at
something it cannot honour; it does not scan the type first, because that would
be a full type walk on every call. So ``validate(1, list["JSON"])`` raises
``ValidationError`` — 1 is not a list, and the bad argument is never consulted —
while ``validate([1], list["JSON"])`` reaches it and raises here.

See :data:`UNSUPPORTED_TYPES` for the type-level property, which has no such
caveat.
"""

UNSUPPORTED_TYPES: list[Any] = []
"""
Types that are unsupported, for which ``can_validate`` must be :obj:`False`.

Unlike :data:`UNSUPPORTED` this is a property of the type alone, with no value
involved and no reaching required. Totality lives here.
"""


def _valid(t: Any, *vals: Any) -> None:
    VALID.extend((val, t) for val in vals)


def _invalid(t: Any, *vals: Any) -> None:
    INVALID.extend((val, t) for val in vals)


# Basic types ---------------------------------------------------------------
_valid(bool, True, False)
_invalid(bool, 1, 0, "True", None)
_valid(int, 0, 1, -1, 10**30, True)  # bool is a subclass of int, deliberately
_invalid(int, 1.0, "1", None, [1])
_valid(float, 1.0, -0.5, float("nan"))
_invalid(float, 1, "1.0", None)
_valid(complex, 1j, complex(1, 2))
_invalid(complex, 1.0, 1, "1j")
_valid(str, "", "hi")
_invalid(str, b"hi", 1, None)
_valid(bytes, b"", b"hi")
_invalid(bytes, "hi", bytearray(b"hi"), 1)
_valid(bytearray, bytearray(b"hi"))
_invalid(bytearray, b"hi", "hi")
_valid(memoryview, memoryview(b"hi"))
_invalid(memoryview, b"hi")
_valid(range, range(3))
_invalid(range, [0, 1, 2], (0, 1, 2))
_valid(slice, slice(1, 2))
_invalid(slice, (1, 2))

# None and NoneType ---------------------------------------------------------
_valid(None, None)
_invalid(None, 0, False, "", [])
_valid(type(None), None)
_invalid(type(None), 0, False)

# Any -----------------------------------------------------------------------
_valid(Any, None, 0, "hi", [1, 2], object())

# Bare collection, mapping and tuple types ----------------------------------
_valid(list, [], [1, "a"])
_invalid(list, (), {}, "ab")
_valid(tuple, (), (1, "a"), Point(1, 2))
_invalid(tuple, [], {})
_valid(set, set(), {1})
_invalid(set, frozenset(), [])
_valid(frozenset, frozenset(), frozenset({1}))
_invalid(frozenset, set(), [])
_valid(dict, {}, {"a": 1})
_invalid(dict, [], set())
_valid(collections.deque, collections.deque())
_invalid(collections.deque, [])
_valid(collections.defaultdict, collections.defaultdict(list))
_invalid(collections.defaultdict, {})
_valid(abc.Collection, [], (), set(), {}, "ab")
_invalid(abc.Collection, 1, iter([]))
_valid(abc.Sequence, [], (), "ab")
_invalid(abc.Sequence, set(), {})
_valid(abc.MutableSequence, [])
_invalid(abc.MutableSequence, (), "ab")
_valid(abc.Set, set(), frozenset())
_invalid(abc.Set, [], {})
_valid(abc.MutableSet, set())
_invalid(abc.MutableSet, frozenset())
_valid(abc.Mapping, {}, collections.defaultdict(list))
_invalid(abc.Mapping, [], set())
_valid(abc.MutableMapping, {})
_invalid(abc.MutableMapping, [])
_valid(abc.Iterable, [], (), iter([]), "ab")
_invalid(abc.Iterable, 1, None)
_valid(abc.Iterator, iter([]), iter({}))
_invalid(abc.Iterator, [], ())
_valid(abc.Container, [], (), set(), {})
_invalid(abc.Container, 1, iter([]))
_valid(abc.Hashable, 1, "a", ())
_invalid(abc.Hashable, [], {})
_valid(abc.Sized, [], "", {})
_invalid(abc.Sized, 1, iter([]))
_valid(abc.Buffer, b"", bytearray(), memoryview(b""))
_invalid(abc.Buffer, "", [])
_valid(ByteString, b"", bytearray(), memoryview(b""))
_invalid(ByteString, "", [])
_valid(list[ByteString], [], [b"", memoryview(b"")])
_invalid(list[ByteString], [""], [b"", 1])

# Parametric collections ----------------------------------------------------
_valid(list[int], [], [1, 2], [True])
_invalid(list[int], [1, "a"], ["a"], (1, 2), [1.0])
_valid(list[list[int]], [], [[]], [[1], [2, 3]])
_invalid(list[list[int]], [[1], ["a"]], [1])
_valid(set[int], set(), {1, 2})
_invalid(set[int], {1, "a"}, frozenset({1}))
_valid(frozenset[str], frozenset(), frozenset({"a"}))
_invalid(frozenset[str], frozenset({1}), {"a"})
_valid(collections.deque[int], collections.deque([1, 2]))
_invalid(collections.deque[int], collections.deque(["a"]), [1])
_valid(abc.Collection[int], [1], (1,), {1})
_invalid(abc.Collection[int], ["a"], 1)
_valid(abc.Sequence[int], [1], (1,))
_invalid(abc.Sequence[int], {1}, ["a"])
_valid(abc.MutableSequence[int], [1])
_invalid(abc.MutableSequence[int], (1,), ["a"])
_valid(abc.Set[int], {1}, frozenset({1}))
_invalid(abc.Set[int], {"a"}, [1])
_valid(abc.MutableSet[int], {1})
_invalid(abc.MutableSet[int], frozenset({1}), {"a"})

# Parametric mappings -------------------------------------------------------
_valid(dict[str, int], {}, {"a": 1})
_invalid(dict[str, int], {1: 1}, {"a": "b"}, [("a", 1)])
_valid(dict[str, list[int]], {"a": [1]})
_invalid(dict[str, list[int]], {"a": ["b"]})
_valid(abc.Mapping[str, int], {"a": 1})
_invalid(abc.Mapping[str, int], {"a": "b"})
_valid(abc.MutableMapping[str, int], {"a": 1})
_invalid(abc.MutableMapping[str, int], {1: 1})
_valid(
    collections.defaultdict[str, int], collections.defaultdict(int, {"a": 1})
)
_invalid(collections.defaultdict[str, int], {"a": 1})

# Tuples --------------------------------------------------------------------
_valid(tuple[int, str], (1, "a"))
_invalid(tuple[int, str], (1,), (1, "a", 2), ("a", 1), [1, "a"])
_valid(tuple[int, ...], (), (1,), (1, 2, 3))
_invalid(tuple[int, ...], (1, "a"), [1])
_valid(tuple[()], ())
_invalid(tuple[()], (1,))

# Unions --------------------------------------------------------------------
_valid(Union[int, str], 1, "a")
_invalid(Union[int, str], 1.0, None, [1])
_valid(int | str, 1, "a")
_invalid(int | str, 1.0, None)
_valid(Optional[int], 1, None)
_invalid(Optional[int], "a", 1.0)
_valid(int | None, 1, None)
_invalid(int | None, "a")
# Structured members: the sequential-attempt path rather than the isinstance
# tuple. Given [1, "a"], no member validates, and the 1 validating against int
# inside the first attempt must not settle the union.
_valid(list[int] | list[str], [1, 2], ["a"], [])
_invalid(list[int] | list[str], [1, "a"], ("a",), 1)
_valid(list[int] | str, [1], "a")
_invalid(list[int] | str, [1, "a"], 1)
_valid(dict[str, int] | list[int], {"a": 1}, [1])
_invalid(dict[str, int] | list[int], {"a": "b"}, ["a"])
_valid(list[list[int] | str], [[1], "a", []])
_invalid(list[list[int] | str], [[1], 1], [["a"]])

# Literals ------------------------------------------------------------------
_valid(Literal[1, 2], 1, 2)
_invalid(Literal[1, 2], 3, "1", 1.0, True)  # True == 1, but is not an int
_valid(Literal["a"], "a")
_invalid(Literal["a"], "b", b"a")
_valid(Literal[True], True)
_invalid(Literal[True], 1)  # 1 == True, but is not a bool
_valid(Literal[None], None)
_invalid(Literal[None], 0, False)
_valid(Literal[b"x"], b"x")
_invalid(Literal[b"x"], "x")
_valid(Literal[Colour.RED], Colour.RED)
_invalid(Literal[Colour.RED], Colour.GREEN, 1)
_valid(Literal[1, "a", None], 1, "a", None)
_invalid(Literal[1, "a", None], 2, "b", False)

# Type variables ------------------------------------------------------------
_valid(T, 1, "a", None)
_valid(TBound, 1, True)
_invalid(TBound, "a", 1.0)
_valid(TConstrained, 1, "a")
_invalid(TConstrained, 1.0, None)  # v1 ignored constraints entirely

# TypedDict -----------------------------------------------------------------
_valid(Movie, {"title": "Jaws", "year": 1975})
_invalid(
    Movie,
    {"title": "Jaws"},
    {"title": "Jaws", "year": "1975"},
    {"year": 1975},
    [],
    {1: "Jaws"},
)
_invalid(Movie, {"title": "Jaws", "year": 1975, 1: "x"})
_valid(Movie, {"title": "Jaws", "year": 1975, "extra": object()})
_valid(PartialMovie, {"title": "Jaws"}, {"title": "Jaws", "year": 1975})
_invalid(PartialMovie, {"title": "Jaws", "year": "1975"}, {})
_invalid(PartialMovie, {"title": "Jaws", 1: 1975})
_valid(QualifiedMovie, {"title": "Jaws", "year": 1975})
_valid(QualifiedMovie, {"title": "Jaws", "year": 1975, "tags": ["shark"]})
_invalid(QualifiedMovie, {"title": "Jaws", "year": 1975, "tags": [1]})
_invalid(QualifiedMovie, {"title": "Jaws"})
_valid(NestedMovie, {"title": "Jaws"})
_valid(NestedMovie, {"title": "Jaws", "sequel": {"title": "Jaws 2"}})
_invalid(NestedMovie, {"title": "Jaws", "sequel": {"year": 1978}})

# TypedDicts defined with typing_extensions, which typing.is_typeddict does not
# recognise. The package comes with the type checker, so it is normally here.
if importlib.util.find_spec("typing_extensions") is not None:
    import typing_extensions

    class ExtensionsMovie(typing_extensions.TypedDict):
        title: str
        year: typing_extensions.NotRequired[int]

    class NestedExtensionsMovie(typing_extensions.TypedDict):
        title: str
        sequel: typing_extensions.NotRequired["NestedExtensionsMovie"]

    _valid(ExtensionsMovie, {"title": "Jaws"}, {"title": "Jaws", "year": 1975})
    _invalid(
        ExtensionsMovie,
        {"title": "Jaws", "year": "1975"},
        {"year": 1975},
        {"title": "Jaws", 1: 2},
        [],
    )
    _valid(NestedExtensionsMovie, {"title": "Jaws", "sequel": {"title": "2"}})
    _invalid(NestedExtensionsMovie, {"title": "Jaws", "sequel": {"year": 1978}})

# Closed TypedDicts and extra items (PEP 728). The class records only its own
# arguments, so inheritance is the part a validator has to work out.
if sys.version_info >= (3, 15):
    from typing import Never

    class Closed(TypedDict, closed=True):
        x: int

    class InheritsClosed(Closed):
        pass

    # A type checker rejects the next two definitions. The runtime accepts them,
    # and a class's own keys and arguments are what it is validated by.
    class ExtendsClosed(Closed):
        y: int  # type: ignore[misc]

    class Reopened(Closed, closed=False):  # type: ignore[misc]
        pass

    class ExtraInts(TypedDict, extra_items=int):  # type: ignore[call-arg]
        x: str

    class InheritsExtraInts(ExtraInts):
        pass

    class ReadOnlyExtras(TypedDict, extra_items=ReadOnly[int]):  # type: ignore[call-arg]
        x: str

    class NeverExtras(TypedDict, extra_items=Never):  # type: ignore[call-arg]
        x: int

    class NoneExtras(TypedDict, extra_items=None):  # type: ignore[call-arg]
        x: int

    class Tree(TypedDict, extra_items="Tree"):  # type: ignore[call-arg]
        value: int

    ClosedFunctional = TypedDict("ClosedFunctional", {"x": int}, closed=True)

    class ClosedY(TypedDict, closed=True):
        y: int

    class Conflicted(ClosedY, ExtraInts):  # type: ignore[misc]
        pass

    class CallableExtras(TypedDict, extra_items=Callable[[int], int]):  # type: ignore[call-arg]
        x: int

    class DanglingExtras(  # type: ignore[call-arg]
        TypedDict, extra_items="NeverDefinedAnywhere"
    ):
        x: int

    _valid(Closed, {"x": 1})
    _invalid(Closed, {"x": 1, "y": 2}, {"x": 1, 2: 3}, {})
    _valid(InheritsClosed, {"x": 1})
    _invalid(InheritsClosed, {"x": 1, "y": 2})
    _valid(ExtendsClosed, {"x": 1, "y": 2})
    _invalid(ExtendsClosed, {"x": 1, "y": 2, "z": 3})
    _valid(Reopened, {"x": 1, "y": object()})
    _valid(ExtraInts, {"x": "a"}, {"x": "a", "y": 1, "z": True})
    _invalid(ExtraInts, {"x": "a", "y": "b"}, {"x": 1}, {"x": "a", 1: 1})
    _valid(InheritsExtraInts, {"x": "a", "y": 2})
    _invalid(InheritsExtraInts, {"x": "a", "y": "b"})
    _valid(ReadOnlyExtras, {"x": "a", "y": 1})
    _invalid(ReadOnlyExtras, {"x": "a", "y": "b"})
    _valid(NeverExtras, {"x": 1})
    _invalid(NeverExtras, {"x": 1, "y": 2})
    _valid(NoneExtras, {"x": 1}, {"x": 1, "y": None})
    _invalid(NoneExtras, {"x": 1, "y": 0})
    _valid(
        Tree,
        {"value": 1},
        {"value": 1, "left": {"value": 2, "a": {"value": 3}}},
    )
    _invalid(
        Tree, {"value": 1, "left": {"value": "x"}}, {"value": 1, "left": 3}
    )
    _valid(ClosedFunctional, {"x": 1})
    _invalid(ClosedFunctional, {"x": 1, "y": 2})
    _valid(list[Closed], [{"x": 1}, {"x": 2}])
    _invalid(list[Closed], [{"x": 1}, {"x": 2, "y": 3}])
    _valid(dict[str, ExtraInts], {"k": {"x": "a", "y": 1}})
    _invalid(dict[str, ExtraInts], {"k": {"x": "a", "y": "b"}})

# Sentinels (PEP 661), a builtin from 3.15, which stand for themselves.
if sys.version_info >= (3, 15):
    MISSING = sentinel("MISSING")
    OTHER = sentinel("OTHER")
    _valid(MISSING, MISSING)
    _invalid(MISSING, OTHER, sentinel("MISSING"), None, "MISSING")
    _valid(int | MISSING, 1, MISSING)
    _invalid(int | MISSING, "a", None, OTHER)
    _valid(MISSING | None, None, MISSING)
    _valid(list[int | MISSING], [], [1, MISSING])
    _invalid(list[int | MISSING], [1, OTHER])
    _valid(dict[str, str | MISSING], {"a": "b", "c": MISSING})
    _invalid(dict[str, str | MISSING], {"a": OTHER})

# typing_extensions.Sentinel, which is how 3.14 spells them.
if importlib.util.find_spec("typing_extensions") is not None and hasattr(
    typing_extensions, "Sentinel"
):
    EXTENSIONS_MISSING = typing_extensions.Sentinel("EXTENSIONS_MISSING")
    _valid(EXTENSIONS_MISSING, EXTENSIONS_MISSING)
    _invalid(EXTENSIONS_MISSING, None, 1, "EXTENSIONS_MISSING")

# frozendict, a builtin from 3.15 (PEP 814), checked as a mapping.
if sys.version_info >= (3, 15):
    _valid(frozendict, frozendict(), frozendict({"a": 1}))
    _invalid(frozendict, {}, [])
    _valid(frozendict[str, int], frozendict(), frozendict({"a": 1, "b": 2}))
    _invalid(
        frozendict[str, int],
        frozendict({"a": "x"}),
        frozendict({1: 1}),
        {"a": 1},
    )
    _valid(dict[str, frozendict[str, int]], {"k": frozendict({"a": 1})})
    _invalid(dict[str, frozendict[str, int]], {"k": frozendict({"a": "x"})})
    _valid(abc.Mapping[str, int], frozendict({"a": 1}))

# The same, defined with typing_extensions, which is how 3.14 spells them.
if importlib.util.find_spec("typing_extensions") is not None:

    class ExtensionsClosed(typing_extensions.TypedDict, closed=True):
        x: int

    class ExtensionsInheritsClosed(ExtensionsClosed):
        pass

    class ExtensionsExtraInts(typing_extensions.TypedDict, extra_items=int):  # type: ignore[call-arg]
        x: str

    _valid(ExtensionsClosed, {"x": 1})
    _invalid(ExtensionsClosed, {"x": 1, "y": 2})
    _valid(ExtensionsInheritsClosed, {"x": 1})
    _invalid(ExtensionsInheritsClosed, {"x": 1, "y": 2})
    _valid(ExtensionsExtraInts, {"x": "a", "y": 1})
    _invalid(ExtensionsExtraInts, {"x": "a", "y": "b"})

# NamedTuple ----------------------------------------------------------------
_valid(NamedTuple, Point(1, 2), LegacyPoint(1, 2))
_invalid(NamedTuple, (1, 2), 1, "ab", [1, 2])
_valid(Point, Point(1, 2))
# A named tuple can be built with the wrong field types — nothing checks at
# construction — which is the entire reason validating the fields is worth doing.
_invalid(
    Point,
    Point("a", 2),  # type: ignore[arg-type]
    (1, 2),
    Tagged("a", []),
)
_valid(Tagged, Tagged("a", [1]))
_invalid(
    Tagged,
    Tagged("a", ["b"]),  # type: ignore[list-item]
    Tagged(1, []),  # type: ignore[arg-type]
)

# Type[T] and type ----------------------------------------------------------
_valid(type, int, Plain, type)
_invalid(type, 1, "int", None)
_valid(type[int], int, bool)
_invalid(type[int], str, 1, object)
_valid(type[Union[int, str]], int, str, bool)
_invalid(type[Union[int, str]], float, 1)
_valid(type[Any], int, Plain)
_invalid(type[Any], 1)
_valid(type[Shape], Shape, Square)
_invalid(type[Shape], int, Square())
_valid(type[Colour], Colour)
_invalid(type[Colour], int, Colour.RED)
_valid(type[Sized], list, str, dict)
_invalid(type[Sized], int)
_valid(type[Union[Shape, int]], Square, int, bool)
_invalid(type[Union[Shape, int]], str, Square())

# Protocols -----------------------------------------------------------------
_valid(Sized, [], "", {})
_invalid(Sized, 1, None)

# Generic classes -----------------------------------------------------------
# The arguments are not checked, deliberately: a generic class does not, in
# general, expose enough at runtime to determine them.
_valid(Box[int], Box(1), Box("a"))
_invalid(Box[int], 1, None)
_valid(SubList, SubList())
_invalid(SubList, [])

# Type aliases --------------------------------------------------------------
_valid(MyInt, 1, True)
_invalid(MyInt, "a", 1.0)
_valid(Aliased, 1, "a")
_invalid(Aliased, 1.0)
_valid(JSON, 1, "a", True, None, [], [1, "a"], {"a": [1, {"b": None}]})
_invalid(JSON, 1.0, [1.0], {"a": 1.0}, {1: "a"}, object())
_valid(Pair[int], (1, 2))
_invalid(Pair[int], (1, "a"), (1,), [1, 2])

# Annotated -----------------------------------------------------------------
# Validates as the underlying type; the metadata is not checked.
_valid(Annotated[int, "positive"], 1, -1)
_invalid(Annotated[int, "positive"], "a", 1.0)
_valid(Annotated[list[int], "m"], [1])
_invalid(Annotated[list[int], "m"], ["a"])
_valid(Annotated[int, {"ge": 0}], 1)  # unhashable metadata, still supported
_invalid(Annotated[int, {"ge": 0}], "a")

# NewType -------------------------------------------------------------------
_valid(UserId, 1, True)
_invalid(UserId, "a", 1.0)
_valid(Nested, 1)
_invalid(Nested, "a")

# Iterators and iterables ---------------------------------------------------
# Iterator[T] cannot check its items without consuming them, so it does not.
_valid(Iterator[int], iter([1]), iter(["a"]))
_invalid(Iterator[int], [1], (1,))
# Iterable[T] checks items exactly when the value is a Collection. v1 intended
# this and a dispatch-order bug made the code unreachable, so [1, "a"] failed
# Collection[int] but passed Iterable[int].
_valid(Iterable[int], [1, 2], (1,), {1}, iter(["a"]))
_invalid(Iterable[int], [1, "a"], ["a"], 1)
_valid(abc.Container[int], [1], (1,))
_invalid(abc.Container[int], [1, "a"])

# --------------------------------------------------------------------------
# Unsupported forms.
# --------------------------------------------------------------------------

UNSUPPORTED_TYPES.extend(
    [
        Callable[[int], int],
        Callable[..., int],
        Self,
        NotRuntime,
        list["JSON"],  # inline forward reference: no owner to resolve against
        "JSON",
        BadMovie,
        BadPoint,
        collections.namedtuple,  # a factory function, not a type
        type[list[int]],  # issubclass cannot express it
        type[Movie],  # issubclass refuses a TypedDict
        type[NotRuntime],
        type[HasX],  # issubclass refuses a protocol with data members
        type[Union[Square, Movie]],
        type[Union[abc.Hashable, Movie]],
        object(),
        42,
        list[Callable[[int], int]],  # poisoned by its item type
        dict[str, Self],  # type: ignore[misc]
    ]
)


def _unsupported(t: Any, *vals: Any) -> None:
    UNSUPPORTED.extend((val, t) for val in vals)


# Each value is one that reaches the unsupported component.
_unsupported(Callable[[int], int], lambda x: x, 1, None)
_unsupported(Callable[..., int], lambda: 1, "a")
_unsupported(Self, 1, None, object())
_unsupported(NotRuntime, 1, None)
_unsupported(list["JSON"], [1], ["a", 2])
_unsupported("JSON", 1, None)
_unsupported(BadMovie, {"title": "Jaws", "other": 1})
_unsupported(BadPoint, BadPoint(1, 2))
_unsupported(collections.namedtuple, 1, None)
_unsupported(type[list[int]], int, list)
_unsupported(type[Movie], dict, 1)
_unsupported(type[NotRuntime], Plain, 1)
_unsupported(type[HasX], Plain, 1)
_unsupported(type[Union[Square, Movie]], Square, 1)
_unsupported(type[Union[abc.Hashable, Movie]], int, list, 1)
_unsupported(object(), 1, None)
_unsupported(42, 1, None)
_unsupported(list[Callable[[int], int]], [lambda: 1])
_unsupported(dict[str, Self], {"a": 1})  # type: ignore[misc]

if sys.version_info >= (3, 15):
    UNSUPPORTED_TYPES.extend([Conflicted, CallableExtras, DanglingExtras])
    # Conflicting settings make the TypedDict itself unsupported, so every value
    # reaches it. An unsupported extra-items type is reached by an extra key.
    _unsupported(Conflicted, {"x": "a"}, 1)
    _unsupported(CallableExtras, {"x": 1, "y": lambda v: v})
    _unsupported(DanglingExtras, {"x": 1, "y": 1})
