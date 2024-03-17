# pylint: disable = missing-docstring

from collections import deque, defaultdict
import collections.abc as collections_abc
import sys
import typing
import pytest

from typing_validation import validate, validation_aliases
from typing_validation.validation import (
    _pseudotypes,
    _pseudotypes_dict,
    _is_typed_dict,
)

if sys.version_info[1] >= 8:
    from typing import Literal
else:
    from typing_extensions import Literal

if sys.version_info[1] >= 9:
    from typing import TypedDict
else:
    from typing_extensions import TypedDict

if sys.version_info[1] >= 10:
    from types import UnionType
else:
    UnionType = None

_basic_types = [
    bool,
    int,
    float,
    complex,
    str,
    bytes,
    bytearray,
    list,
    tuple,
    set,
    frozenset,
    dict,
    type(None),
]

_all_types = _basic_types + sorted(_pseudotypes, key=repr)

_basic_cases = (
    (True, [bool, int, typing.Hashable]),
    (12, [int, typing.Hashable]),
    (13.5, [float, typing.Hashable]),
    (1 + 2j, [complex, typing.Hashable]),
    (None, [None, type(None), typing.Hashable]),
)

_collection_cases: typing.Tuple[
    typing.Tuple[typing.Any, typing.List[typing.Any]], ...
] = (
    (
        "hello",
        [
            str,
            typing.Collection,
            typing.Collection[str],
            typing.Sequence,
            typing.Sequence[str],
            typing.Iterable,
            typing.Sized,
            typing.Hashable,
            typing.Container,
        ],
    ),
    (
        b"hello",
        [
            bytes,
            typing.Collection,
            typing.Collection[int],
            typing.Sequence,
            typing.Sequence[int],
            typing.Iterable,
            typing.Container,
            typing.Sized,
            typing.Hashable,
            *(
                [typing.ByteString]
                if sys.version_info[1] <= 11
                else [typing.cast(typing.Any, collections_abc.Buffer)]
            ),
        ],
    ),
    (
        [0, 1, 2],
        [
            list,
            typing.List,
            typing.List[int],
            typing.Collection,
            typing.Collection[int],
            typing.Sequence,
            typing.Sequence[int],
            typing.MutableSequence,
            typing.MutableSequence[int],
            typing.Iterable,
            typing.Iterable[int],
            typing.Sized,
            typing.Container,
        ],
    ),
    (
        (0, 1, 2),
        [
            tuple,
            typing.Tuple,
            typing.Tuple[int, int, int],
            typing.Tuple[int, ...],
            typing.Collection,
            typing.Collection[int],
            typing.Sequence,
            typing.Sequence[int],
            typing.Iterable,
            typing.Iterable[int],
            typing.Sized,
            typing.Hashable,
            typing.Container,
        ],
    ),
    (
        {0, 1, 2},
        [
            set,
            typing.Set,
            typing.Set[int],
            typing.Collection,
            typing.Collection[int],
            typing.AbstractSet,
            typing.AbstractSet[int],
            typing.MutableSet,
            typing.MutableSet[int],
            typing.Iterable,
            typing.Iterable[int],
            typing.Sized,
            typing.Container,
        ],
    ),
    (
        frozenset({0, 1, 2}),
        [
            frozenset,
            typing.FrozenSet,
            typing.FrozenSet[int],
            typing.Collection,
            typing.Collection[int],
            typing.AbstractSet,
            typing.AbstractSet[int],
            typing.Iterable,
            typing.Iterable[int],
            typing.Sized,
            typing.Hashable,
            typing.Container,
        ],
    ),
    (
        deque([0, 1, 2]),
        [
            deque,
            typing.Deque,
            typing.Deque[int],
            typing.Collection,
            typing.Collection[int],
            typing.Sequence,
            typing.Sequence[int],
            typing.MutableSequence,
            typing.MutableSequence[int],
            typing.Iterable,
            typing.Iterable[int],
            typing.Sized,
            typing.Container,
        ],
    ),
)

_mapping_cases = (
    (
        {"a": 0, "b": 1},
        [
            dict,
            typing.Collection,
            typing.Collection[str],
            typing.Dict,
            typing.Dict[str, int],
            typing.Mapping,
            typing.Mapping[str, int],
            typing.MutableMapping,
            typing.MutableMapping[str, int],
            typing.Iterable,
            typing.Iterable[str],
            typing.Sized,
            typing.Container,
        ],
    ),
    (
        defaultdict(lambda: 0, {"a": 0, "b": 1}),
        [
            defaultdict,
            typing.Collection,
            typing.Collection[str],
            typing.Dict,
            typing.Dict[str, int],
            typing.DefaultDict,
            typing.DefaultDict[str, int],
            typing.Mapping,
            typing.Mapping[str, int],
            typing.MutableMapping,
            typing.MutableMapping[str, int],
            typing.Iterable,
            typing.Iterable[str],
            typing.Sized,
            typing.Container,
        ],
    ),
)

_test_cases = _basic_cases + _collection_cases + _mapping_cases


@pytest.mark.parametrize("val, ts", _test_cases)
def test_valid_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    ts = ts + [_pseudotypes_dict[t] for t in ts if t in _pseudotypes_dict]
    for t in ts:
        validate(val, t)
        validate(val, typing.Optional[t])
        validate(val, typing.Any)


@pytest.mark.parametrize("val, ts", _test_cases)
def test_invalid_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    ts = ts + [_pseudotypes_dict[t] for t in ts if t in _pseudotypes_dict]
    for t in [t for t in _all_types if t not in ts]:
        try:
            validate(val, t)
            assert (
                False
            ), f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
        except TypeError:
            pass


_specific_invalid_cases = (
    (
        "hello",
        [
            typing.Collection[int],
            typing.Sequence[int],
            typing.List[str],
            typing.Deque[str],
            typing.Tuple[str, ...],
            typing.Tuple[str, str, str, str, str],
            typing.Dict[int, str],
        ],
    ),
    (
        b"hello",
        [
            typing.Collection[str],
            typing.Sequence[str],
            typing.List[int],
            typing.Deque[int],
            typing.Tuple[int, ...],
            typing.Dict[int, int],
        ],
    ),
    (
        [0, 1, 2],
        [
            typing.List[str],
            typing.Collection[str],
            typing.Sequence[str],
            typing.MutableSequence[str],
        ],
    ),
    (
        (0, 1, 2),
        [
            typing.Tuple[str, int, int],
            typing.Tuple[int, str, int],
            typing.Tuple[int, int, str],
            typing.Tuple[int, int],
            typing.Tuple[int, int, int, int],
            typing.Tuple[str, ...],
            typing.Collection[str],
            typing.Sequence[str],
            typing.List[int],
            typing.Deque[int],
            typing.Dict[int, int],
        ],
    ),
    (
        {0, 1, 2},
        [
            typing.Set[str],
            typing.Collection[str],
            typing.Sequence[str],
            typing.MutableSet[str],
            typing.List[int],
            typing.Deque[int],
            typing.Dict[int, int],
            typing.FrozenSet[int],
        ],
    ),
    (
        frozenset({0, 1, 2}),
        [
            typing.FrozenSet[str],
            typing.Collection[str],
            typing.Sequence[str],
            typing.List[int],
            typing.Deque[int],
            typing.Dict[int, int],
            typing.Set[int],
        ],
    ),
    (
        deque([0, 1, 2]),
        [
            typing.Deque[str],
            typing.Collection[str],
            typing.Sequence[str],
            typing.MutableSequence[str],
            typing.List[int],
            typing.Dict[int, int],
            typing.Set[int],
            typing.FrozenSet[int],
        ],
    ),
    (
        {"a": 0, "b": 1},
        [
            typing.Collection[int],
            typing.Dict[str, str],
            typing.Dict[int, int],
            typing.Mapping[str, str],
            typing.Mapping[int, int],
            typing.MutableMapping[str, str],
            typing.MutableMapping[int, int],
            typing.List[str],
            typing.Deque[str],
            typing.Set[str],
            typing.FrozenSet[str],
        ],
    ),
    (
        defaultdict(lambda: 0, {"a": 0, "b": 1}),
        [
            typing.Collection[int],
            typing.Dict[str, str],
            typing.Dict[int, int],
            typing.DefaultDict[str, str],
            typing.DefaultDict[int, int],
            typing.Mapping[str, str],
            typing.Mapping[int, int],
            typing.MutableMapping[str, str],
            typing.MutableMapping[int, int],
            typing.List[str],
            typing.Deque[str],
            typing.Set[str],
            typing.FrozenSet[str],
        ],
    ),
)


@pytest.mark.parametrize("val, ts", _specific_invalid_cases)
def test_specific_invalid_cases(
    val: typing.Any, ts: typing.List[typing.Any]
) -> None:
    ts = ts + [_pseudotypes_dict[t] for t in ts if t in _pseudotypes_dict]
    for t in ts:
        try:
            validate(val, t)
            assert (
                False
            ), f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
        except TypeError:
            pass


_union_cases: typing.Tuple[
    typing.Tuple[typing.Any, typing.List[typing.Any]], ...
]
_union_cases = (
    (0, [typing.Union[str, int], typing.Union[int, str], typing.Optional[int]]),
    (
        "hello",
        [typing.Union[str, int], typing.Union[int, str], typing.Optional[str]],
    ),
)

if sys.version_info[1] >= 10:
    _union_cases += (
        (0, [str | int, int | str, int | None]),
        ("hello", [str | int, int | str, str | None]),
    )


@pytest.mark.parametrize("val, ts", _union_cases)
def test_union_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    for t in ts:
        validate(val, t)


_invalid_union_cases = (
    (0, [typing.Union[str, bool], typing.Optional[str]]),
    ("hello", [typing.Union[bool, int], typing.Optional[int]]),
)


@pytest.mark.parametrize("val, ts", _invalid_union_cases)
def test_invalid_union_cases(
    val: typing.Any, ts: typing.List[typing.Any]
) -> None:
    for t in ts:
        try:
            validate(val, t)
            assert (
                False
            ), f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
        except TypeError:
            pass


_literal_cases = (
    ("0", [Literal["0", "1", 2], Literal["0"], Literal["hello", 0, "0"]]),
    (0, [Literal[0, "1", 2], Literal[0], Literal["hello", 0, "0"]]),
)


@pytest.mark.parametrize("val, ts", _literal_cases)
def test_literal_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    for t in ts:
        validate(val, t)


_invalid_literal_cases = (
    ("0", [Literal[0, "1", 2], Literal[0], Literal["hello", 1, "1"]]),
    (0, [Literal["0", "1", 2], Literal["0"], Literal["hello", 1, "1"]]),
)


@pytest.mark.parametrize("val, ts", _invalid_literal_cases)
def test_invalid_literal_cases(
    val: typing.Any, ts: typing.List[typing.Any]
) -> None:
    for t in ts:
        try:
            validate(val, t)
            assert (
                False
            ), f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
        except TypeError:
            pass


JSON = typing.Union[
    int, float, bool, None, str, typing.List["JSON"], typing.Dict[str, "JSON"]
]
_validation_aliases = {"JSON": JSON}

_alias_cases = (
    (
        [
            1,
            2.2,
        ],
        {"JSON"},
    ),
    ([1, 2.2, {"a": False}], {"JSON"}),
    ([1, 2.2, {"a": ["1", None, {"b": False}]}], {"JSON"}),
)


@pytest.mark.parametrize("val, ts", _alias_cases)
def test_alias_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    for t in ts:
        with validation_aliases(**_validation_aliases):
            validate(val, t)


_invalid_alias_cases = (
    (b"Hello", {"JSON"}),
    ([1, None, b"Hello", 2.2], {"JSON"}),
    ({"a": 1, "b": b"Hello"}, {"JSON"}),
    ({"a": 1, 2: "Hello"}, {"JSON"}),
    ([1, None, {"a": b"Hello"}, 2.2], {"JSON"}),
)


@pytest.mark.parametrize("val, ts", _invalid_alias_cases)
def test_invalid_alias_cases(
    val: typing.Any, ts: typing.List[typing.Any]
) -> None:
    for t in ts:
        try:
            with validation_aliases(**_validation_aliases):
                validate(val, t)
            assert (
                False
            ), f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
        except TypeError:
            pass


class TD1(TypedDict, total=True):
    x: int
    y: float


class TD1a(TD1, total=False):
    z: typing.List[str]


class TD1b(TD1, total=True):
    z: typing.List[str]


class TD2(TypedDict, total=False):
    x: str
    w: typing.List[str]

_typed_dict_cases: typing.Dict[typing.Any, typing.List[typing.Any]] = {}
_typed_dict_cases[TD1b] = [
    {"x": 1, "y": 1.5, "z": ["hello", "bye bye"]},
]
_typed_dict_cases[TD1a] = [
    *_typed_dict_cases[TD1b],
    {"x": 1, "y": 1.5},
]
_typed_dict_cases[TD1] = [
    *_typed_dict_cases[TD1a],
    {"x": 1, "y": 1.5, "z": [0, 1, 2]},
]
_typed_dict_cases[TD2] = [
    {"x": "hello", "w": ["hello", "bye bye"]},
    {"x": "hello"},
    {"w": ["hello", "bye bye"]},
    {},
]

if sys.version_info[1] >= 11:
    from typing import Required, NotRequired

    class TD3(TypedDict, total=False):
        x: Required[str] # pyright: ignore
        w: typing.List[str]


    class TD4(TypedDict):
        x: str
        w: NotRequired[typing.List[str]] # pyright: ignore

    _typed_dict_cases[TD3] = [
        {"x": "hello", "w": ["hello", "bye bye"]},
        {"x": "hello"},
    ]
    _typed_dict_cases[TD4] = [
        {"x": "hello", "w": ["hello", "bye bye"]},
        {"x": "hello"},
    ]


@pytest.mark.parametrize("t, vals", _typed_dict_cases.items())
def test_typed_dict_cases(t: typing.Any, vals: typing.List[typing.Any]) -> None:
    assert _is_typed_dict(t), t
    for val in vals:
        validate(val, t)


_invalid_typed_dict_cases: typing.Dict[typing.Any, typing.List[typing.Any]] = {}
_invalid_typed_dict_cases[TD1] = [
    {"x": 1, "y": "invalid"},
    {"x": "invalid", "y": 1.5},
    {"x": 1},
    {"y": 1.5},
    {},
]
_invalid_typed_dict_cases[TD1a] = [
    *_invalid_typed_dict_cases[TD1],
    {"x": 1, "y": 1.5, "z": [0, 1, 2]},
]
_invalid_typed_dict_cases[TD1b] = [
    *_invalid_typed_dict_cases[TD1a],
    {"x": 1, "y": 1.5},
]
_invalid_typed_dict_cases[TD2] = [
    {"x": "hello", "w": 0},
    {"x": 0, "w": ["hello", "bye bye"]},
    {"w": 0},
    {"x": 0},
]


if sys.version_info[1] >= 11:

    _invalid_typed_dict_cases[TD3] = [
        *_invalid_typed_dict_cases[TD2],
        {"w": ["hello", "bye bye"]},
        {},
    ]
    _invalid_typed_dict_cases[TD4] = [
        *_invalid_typed_dict_cases[TD2],
        {"w": ["hello", "bye bye"]},
        {},
    ]


@pytest.mark.parametrize("t, vals", _invalid_typed_dict_cases.items())
def test_invalid_typed_dict_cases(
    t: typing.Any, vals: typing.List[typing.Any]
) -> None:
    assert _is_typed_dict(t), t
    for val in vals:
        try:
            validate(val, t)
            assert (
                False
            ), f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
        except TypeError:
            pass


S = typing.TypeVar("S", bound=str)
T = typing.TypeVar("T")
U_co = typing.TypeVar("U_co", covariant=True)


class A: ...


class B(typing.Generic[T]):
    def __init__(self, t: T) -> None: ...


class C(typing.Generic[S, T, U_co]):
    def __init__(self, s: S, t: T, u: U_co) -> None: ...


_user_class_cases = (
    (A(), [A]),
    (B(10), [B, B[int]]),
    (C("hello", 20, 30), [C, C[str, int, typing.Union[int, str]]]),
)


@pytest.mark.parametrize("val, ts", _user_class_cases)
def test_user_class_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    for t in ts:
        validate(val, t)


def test_numpy_array() -> None:
    # pylint: disable = import-outside-toplevel
    import numpy as np
    import numpy.typing as npt

    val = np.zeros(5, dtype=np.uint8)
    validate(val, npt.NDArray[np.uint8])
    validate(val, npt.NDArray[typing.Union[np.uint8, np.float32]])
    validate(val, npt.NDArray[typing.Union[typing.Any, np.float32]])
    validate(val, npt.NDArray[typing.Any])
    validate(
        val,
        npt.NDArray[
            typing.Union[
                np.float32,
                typing.Union[np.uint16, typing.Union[np.int8, typing.Any]],
            ]
        ],
    )
    if sys.version_info[1] >= 9:
        validate(val, npt.NDArray[np.number[typing.Any]])
        validate(val, npt.NDArray[np.integer[typing.Any]])
        validate(val, npt.NDArray[np.unsignedinteger[typing.Any]])
        validate(val, npt.NDArray[np.generic])


def test_numpy_array_error() -> None:
    # pylint: disable = import-outside-toplevel
    import numpy as np
    import numpy.typing as npt

    val = np.zeros(5, dtype=np.uint8)
    with pytest.raises(TypeError):
        validate(val, npt.NDArray[typing.Union[np.uint16, np.float32]])
    with pytest.raises(TypeError):
        validate(val, npt.NDArray[np.str_])


def test_typevar() -> None:
    T = typing.TypeVar("T")
    validate(10, T)
    validate(None, T)
    validate([0, "hello"], T)
    IntT = typing.TypeVar("IntT", bound=int)
    validate(10, IntT)
    with pytest.raises(TypeError):
        validate(None, IntT)
    with pytest.raises(TypeError):
        validate([0, 1], IntT)
    IntStrSeqT = typing.TypeVar(
        "IntStrSeqT", bound=typing.Sequence[typing.Union[int, str]]
    )
    validate([0, "hello"], IntStrSeqT)
    validate("Hello", IntStrSeqT)
    with pytest.raises(TypeError):
        validate(0, IntStrSeqT)


def test_subtype() -> None:
    validate(int, type)
    validate(int, typing.Type)
    validate(int, typing.Type[int])
    validate(int, typing.Type[typing.Any])
    validate(int, typing.Type[typing.Union[float, str, typing.Any]])
    validate(int, typing.Type[typing.Union[int, str]])
    with pytest.raises(TypeError):
        validate(int, typing.Type[typing.Union[str, float]])
    with pytest.raises(TypeError):
        validate(10, typing.Type[int])
    with pytest.raises(TypeError):
        validate(10, typing.Type[typing.Union[str, float]])


@pytest.mark.parametrize("val, ts", _union_cases)
def test_union_type_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    if UnionType is not None:
        for t in ts:
            members = t.__args__
            if not members:
                continue
            u = members[0]
            for t in members[1:]:
                u |= t
            validate(val, u)
