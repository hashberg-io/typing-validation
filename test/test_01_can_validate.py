# pylint: disable = missing-docstring, expression-not-assigned

from types import NoneType
import typing
import pytest

from typing_validation.validation import (can_validate, validation_aliases, _pseudotypes_dict)
from .test_00_validate import _test_cases, _union_cases, _literal_cases, _alias_cases, _validation_aliases, _typed_dict_cases

def assert_recorded_type(t: typing.Any) -> None:
    _t = can_validate(t).recorded_type
    if t is NoneType:
        assert None is _t
    elif hasattr(t, "__origin__") and hasattr(t, "__args__") and t.__module__ == "typing":
        assert t.__origin__[*t.__args__] == _t
    else:
        assert t == _t


@pytest.mark.parametrize("val, ts", _test_cases)
def test_valid_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    ts = ts+[_pseudotypes_dict[t] for t in ts if t in _pseudotypes_dict]
    for t in ts:
        assert can_validate(t), f"Should be able to validate {t}"
        assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
        str(can_validate(t))
        assert_recorded_type(t)
    assert can_validate(typing.Any), f"Should be able to validate {typing.Any}"

@pytest.mark.parametrize("val, ts", _union_cases+_literal_cases)
def test_other_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    for t in ts:
        assert can_validate(t), f"Should be able to validate {t}"
        assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
        str(can_validate(t))
        assert_recorded_type(t)

@pytest.mark.parametrize("val, ts", _alias_cases)
def test_alias_cases(val: typing.Any, ts: typing.List[typing.Any]) -> None:
    for t in ts:
        with validation_aliases(**_validation_aliases):
            assert can_validate(t), f"Should be able to validate {t}"
            assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
            str(can_validate(t))
            assert_recorded_type(t)

@pytest.mark.parametrize("t, vals", _typed_dict_cases.items())
def test_typed_dict_cases(t: typing.Any, vals: typing.List[typing.Any]) -> None:
    with validation_aliases(**_validation_aliases):
        assert can_validate(t), f"Should be able to validate {t}"
        assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
        str(can_validate(t))
        assert_recorded_type(t)
