# pylint: disable = missing-docstring

import typing

import pytest

from typing_validation.validation import validated_iter

_iter_cases = [
    ((2*x for x in range(5)), typing.Iterable),
    ((2*x for x in range(5)), typing.Iterator),
    ((2*x for x in range(5)), typing.Iterable[int]),
    ((2*x for x in range(5)), typing.Iterator[int]),
]

@pytest.mark.parametrize("it, t", _iter_cases)
def test_iter_cases(it: typing.Any, t: typing.Any) -> None:
    _it = validated_iter(it, t)
    list(_it)

_invalid_iter_cases = [
    ((typing.cast(typing.Union[int, str], x)*2 for x in ["a", "b", 0, "c"]),
     typing.Iterable[str]),
    ((typing.cast(typing.Union[int, str], x)*2 for x in ["a", "b", 0, "c"]),
     typing.Iterator[str]),
]

@pytest.mark.parametrize("it, t", _invalid_iter_cases)
def test_invalid_typed_dict_cases(it: typing.Any, t: typing.Any) -> None:
    _it = validated_iter(it, t)
    try:
        list(_it)
        assert False, "Iteration should not have succeeded."
    except TypeError:
        pass
