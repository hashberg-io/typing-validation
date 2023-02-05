# pylint: disable = missing-docstring

import typing

import pytest

from typing_validation.validation import (can_validate, validation_aliases, _pseudotypes_dict)
from .test_00_validate import _test_cases, _union_cases, _literal_cases, _alias_cases, _validation_aliases

@pytest.mark.parametrize("val, ts", _test_cases)
def test_valid_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    ts = ts+[_pseudotypes_dict[t] for t in ts if t in _pseudotypes_dict]
    for t in ts:
        assert can_validate(t), f"Should be able to validate {t}"
        assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
    assert can_validate(typing.Any), f"Should be able to validate {typing.Any}"

@pytest.mark.parametrize("val, ts", _union_cases+_literal_cases)
def test_other_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    for t in ts:
        assert can_validate(t), f"Should be able to validate {t}"
        assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"

@pytest.mark.parametrize("val, ts", _alias_cases)
def test_alias_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    for t in ts:
        with validation_aliases(**_validation_aliases):
            assert can_validate(t), f"Should be able to validate {t}"
            assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
