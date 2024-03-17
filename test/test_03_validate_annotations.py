# pylint: disable = missing-docstring

from __future__ import annotations

import sys
import typing
import pytest

from typing_validation import validate
from typing_validation.validation import _is_typed_dict


if sys.version_info[1] >= 9:
    from typing import TypedDict
else:
    from typing_extensions import TypedDict


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
