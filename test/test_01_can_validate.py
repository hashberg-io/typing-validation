# pylint: disable = missing-docstring

import typing

import pytest

from typing_validation.validation import (can_validate, _pseudotypes_dict)
from .test_00_validate import _test_cases, _union_cases, _literal_cases

@pytest.mark.parametrize("val, ts", _test_cases)
def test_valid_cases(val: typing.Any, ts: typing.AbstractSet[typing.Any]) -> None:
    ts = ts|{_pseudotypes_dict[t] for t in ts if t in _pseudotypes_dict}
    for t in ts:
        assert can_validate(t), f"Should be able to validate {t}"
        assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
    assert can_validate(typing.Any), f"Should be able to validate {typing.Any}"

@pytest.mark.parametrize("val, ts", _union_cases)
def test_union_cases(val: typing.Any, ts: typing.AbstractSet[typing.Any]) -> None:
    for t in ts:
        assert can_validate(t), f"Should be able to validate {t}"
        assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"

@pytest.mark.parametrize("val, ts", _literal_cases)
def test_literal_cases(val: typing.Any, ts: typing.AbstractSet[typing.Any]) -> None:
    for t in ts:
        assert can_validate(t), f"Should be able to validate {t}"
        assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
