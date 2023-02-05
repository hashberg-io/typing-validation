# pylint: disable = missing-docstring

from collections import deque, defaultdict
import sys
import typing

import pytest

from typing_validation.validation import (validate, validation_aliases, _pseudotypes, _pseudotypes_dict)

if sys.version_info[1] >= 8:
    from typing import Literal
else:
    from typing_extensions import Literal

_basic_types = [
    bool, int, float, complex, str, bytes, bytearray,
    list, tuple, set, frozenset, dict, type(None)
]

_all_types = _basic_types+list(_pseudotypes) # TODO: make this deterministic by picking a fixed order for pseudotypes

_basic_cases = (
    (True, [bool, int, typing.Hashable]),
    (12, [int, typing.Hashable]),
    (13.5, [float, typing.Hashable]),
    (1+2j, [complex, typing.Hashable]),
    (None, [None, type(None), typing.Hashable]),
)

_collection_cases = (
    ("hello", [str, typing.Collection, typing.Collection[str],
               typing.Sequence, typing.Sequence[str],
               typing.Iterable, typing.Sized, typing.Hashable, typing.Container]),
    (b"hello", [bytes, typing.Collection, typing.Collection[int],
                typing.Sequence, typing.Sequence[int], typing.ByteString,
                typing.Iterable, typing.Container, typing.Sized, typing.Hashable]),
    ([0, 1, 2], [list, typing.List, typing.List[int],
                 typing.Collection, typing.Collection[int],
                 typing.Sequence, typing.Sequence[int],
                 typing.MutableSequence, typing.MutableSequence[int],
                 typing.Iterable, typing.Sized, typing.Container]),
    ((0, 1, 2), [tuple, typing.Tuple, typing.Tuple[int, int, int], typing.Tuple[int, ...],
                 typing.Collection, typing.Collection[int],
                 typing.Sequence, typing.Sequence[int],
                 typing.Iterable, typing.Sized, typing.Hashable, typing.Container]),
    ({0, 1, 2}, [set, typing.Set, typing.Set[int],
                 typing.Collection, typing.Collection[int],
                 typing.AbstractSet, typing.AbstractSet[int],
                 typing.MutableSet, typing.MutableSet[int],
                 typing.Iterable, typing.Sized, typing.Container]),
    (frozenset({0, 1, 2}), [frozenset, typing.FrozenSet, typing.FrozenSet[int],
                            typing.Collection, typing.Collection[int],
                            typing.AbstractSet, typing.AbstractSet[int],
                            typing.Iterable, typing.Sized, typing.Hashable,
                            typing.Container]),
    (deque([0, 1, 2]), [deque, typing.Deque, typing.Deque[int],
                        typing.Collection, typing.Collection[int],
                        typing.Sequence, typing.Sequence[int],
                        typing.MutableSequence, typing.MutableSequence[int],
                        typing.Iterable, typing.Sized, typing.Container]),
)

_mapping_cases = (
    ({"a": 0, "b": 1}, [dict, typing.Collection, typing.Collection[str],
                        typing.Dict, typing.Dict[str, int],
                        typing.Mapping, typing.Mapping[str, int],
                        typing.MutableMapping, typing.MutableMapping[str, int],
                        typing.Iterable, typing.Sized, typing.Container]),
    (defaultdict(lambda: 0, {"a": 0, "b": 1}),
                        [defaultdict, typing.Collection, typing.Collection[str],
                         typing.Dict, typing.Dict[str, int],
                         typing.DefaultDict, typing.DefaultDict[str, int],
                         typing.Mapping, typing.Mapping[str, int],
                         typing.MutableMapping, typing.MutableMapping[str, int],
                         typing.Iterable, typing.Sized, typing.Container,]),
)

_test_cases = _basic_cases+_collection_cases+_mapping_cases

@pytest.mark.parametrize("val, ts", _test_cases)
def test_valid_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    ts = ts+[_pseudotypes_dict[t] for t in ts if t in _pseudotypes_dict]
    for t in ts:
        validate(val, t)
        validate(val, typing.Optional[t])
        validate(val, typing.Any)

@pytest.mark.parametrize("val, ts", _test_cases)
def test_invalid_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    ts = ts+[_pseudotypes_dict[t] for t in ts if t in _pseudotypes_dict]
    for t in [t for t in _all_types if t not in ts]:
        try:
            validate(val, t)
            assert False, f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
        except TypeError:
            pass

_specific_invalid_cases = (
    ("hello", [typing.Collection[int], typing.Sequence[int], typing.List[str], typing.Deque[str],
               typing.Tuple[str, ...], typing.Tuple[str, str, str, str, str], typing.Dict[int, str]]),
    (b"hello", [typing.Collection[str], typing.Sequence[str], typing.List[int], typing.Deque[int],
                typing.Tuple[int, ...], typing.Dict[int, int]]),
    ([0, 1, 2], [typing.List[str], typing.Collection[str], typing.Sequence[str], typing.MutableSequence[str],]),
    ((0, 1, 2), [typing.Tuple[str, int, int], typing.Tuple[int, str, int], typing.Tuple[int, int, str],
                 typing.Tuple[int, int], typing.Tuple[int, int, int, int],
                 typing.Tuple[str, ...], typing.Collection[str], typing.Sequence[str],
                 typing.List[int], typing.Deque[int], typing.Dict[int, int]]),
    ({0, 1, 2}, [typing.Set[str], typing.Collection[str], typing.Sequence[str], typing.MutableSet[str],
                 typing.List[int], typing.Deque[int], typing.Dict[int, int], typing.FrozenSet[int]]),
    (frozenset({0, 1, 2}), [typing.FrozenSet[str], typing.Collection[str], typing.Sequence[str],
                            typing.List[int], typing.Deque[int], typing.Dict[int, int], typing.Set[int],]),
    (deque([0, 1, 2]), [typing.Deque[str], typing.Collection[str], typing.Sequence[str], typing.MutableSequence[str],
                        typing.List[int], typing.Dict[int, int], typing.Set[int], typing.FrozenSet[int],]),
    ({"a": 0, "b": 1}, [typing.Collection[int],
                        typing.Dict[str, str], typing.Dict[int, int],
                        typing.Mapping[str, str], typing.Mapping[int, int],
                        typing.MutableMapping[str, str], typing.MutableMapping[int, int],
                        typing.List[str], typing.Deque[str], typing.Set[str], typing.FrozenSet[str]]),
    (defaultdict(lambda: 0, {"a": 0, "b": 1}), [typing.Collection[int],
                                                typing.Dict[str, str], typing.Dict[int, int],
                                                typing.DefaultDict[str, str], typing.DefaultDict[int, int],
                                                typing.Mapping[str, str], typing.Mapping[int, int],
                                                typing.MutableMapping[str, str], typing.MutableMapping[int, int],
                                                typing.List[str], typing.Deque[str], typing.Set[str], typing.FrozenSet[str]]),
)

@pytest.mark.parametrize("val, ts", _specific_invalid_cases)
def test_specific_invalid_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    ts = ts+[_pseudotypes_dict[t] for t in ts if t in _pseudotypes_dict]
    for t in ts:
        try:
            validate(val, t)
            assert False, f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
        except TypeError:
            pass

_union_cases = (
    (0, [typing.Union[int], typing.Union[str, int], typing.Union[int, str], typing.Optional[int]]),
    ("hello", [typing.Union[str, int], typing.Union[int, str], typing.Optional[str]]),
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
def test_invalid_union_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    for t in ts:
        try:
            validate(val, t)
            assert False, f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
        except TypeError:
            pass


# _iterator_cases = (
#     ("hello", [typing.Iterable[str], typing.Container[str]]),
#     (b"hello", [typing.Iterable[int], typing.Container[int]]),
#     ([0, 1, 2], [typing.Iterable[int], typing.Container[int]]),
#     ((0, 1, 2), [typing.Iterable[int], typing.Container[int]]),
#     ({0, 1, 2}, [typing.Iterable[int], typing.Container[int]]),
#     (frozenset({0, 1, 2}), [typing.Iterable[int], typing.Container[int]]),
#     (deque([0, 1, 2]), [typing.Iterable[int], typing.Container[int]]),
#     ({"a": 0, "b": 1}, [typing.Iterable[str], typing.Container[str]]),
#     (defaultdict(lambda: 0,{"a": 0, "b": 1}), [typing.Iterable[str], typing.Container[str]]),
# )

# @pytest.mark.parametrize("val, ts", _iterator_cases)
# def test_iterator_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
#     for t in ts:
#         validate(val, t)

# _invalid_iterator_cases = (
#     ("hello", [typing.Iterable[int], typing.Container[int]]),
#     (b"hello", [typing.Iterable[str], typing.Container[str]]),
#     ([0, 1, 2], [typing.Iterable[str], typing.Container[str]]),
#     ((0, 1, 2), [typing.Iterable[str], typing.Container[str]]),
#     ({0, 1, 2}, [typing.Iterable[str], typing.Container[str]]),
#     (frozenset({0, 1, 2}), [typing.Iterable[str], typing.Container[str]]),
#     (deque([0, 1, 2]), [typing.Iterable[str], typing.Container[str]]),
#     ({"a": 0, "b": 1}, [typing.Iterable[int], typing.Container[int]]),
#     (defaultdict(lambda: 0, {"a": 0, "b": 1}), [typing.Iterable[int], typing.Container[int]]),
# )

# @pytest.mark.parametrize("val, ts", _invalid_iterator_cases)
# def test_invalid_iterator_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
#     for t in ts:
#         try:
#             validate(val, t)
#             assert False, f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
#         except TypeError:
#             pass

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
def test_invalid_literal_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    for t in ts:
        try:
            validate(val, t)
            assert False, f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
        except TypeError:
            pass

JSON = typing.Union[int, float, bool, None, str, typing.List["JSON"], typing.Dict[str, "JSON"]]
_validation_aliases = {
    "JSON": JSON
}

_alias_cases = (
    ([1, 2.2,], {"JSON"}),
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
def test_invalid_alias_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    for t in ts:
        try:
            with validation_aliases(**_validation_aliases):
                validate(val, t)
            assert False, f"For type {repr(t)}, the following value shouldn't have been an instance: {repr(val)}"
        except TypeError:
            pass
