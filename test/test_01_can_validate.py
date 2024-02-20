# pylint: disable = missing-docstring, expression-not-assigned

import sys
import typing
import pytest

from typing_validation import can_validate, validation_aliases
from typing_validation.inspector import _typing_equiv
from typing_validation.validation import _pseudotypes_dict

from .test_00_validate import _test_cases, _union_cases, _literal_cases, _alias_cases,_typed_dict_cases, _user_class_cases, _validation_aliases

def assert_recorded_type(t: typing.Any) -> None:
    _t = can_validate(t).recorded_type
    if t is type(None):
        assert None is _t
    elif hasattr(t, "__origin__") and hasattr(t, "__args__") and t.__module__ == "typing":
        if sys.version_info[1] <= 8 and t.__origin__ in _typing_equiv:
            t_origin = _typing_equiv[t.__origin__]
        else:
            t_origin = t.__origin__
        if t.__args__:
            assert t_origin[t.__args__] == _t
        else:
            assert t_origin == _t
    else:
        if sys.version_info[1] <= 8 and t in _typing_equiv:
            t = _typing_equiv[t]
        assert t == _t

_valid_cases_ts = sorted({
    t for _, ts in _test_cases for t in ts
}|{
    _pseudotypes_dict[t] for _, ts in _test_cases for t in ts if t in _pseudotypes_dict
}|{typing.Any}, key=repr)

@pytest.mark.parametrize("t", _valid_cases_ts)
def test_valid_cases(t: typing.Any) -> None:
    # ts = ts+[_pseudotypes_dict[t] for t in ts if t in _pseudotypes_dict]
    assert can_validate(t), f"Should be able to validate {t}"
    assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
    str(can_validate(t))
    assert_recorded_type(t)

_other_cases_ts = sorted({
    t for _, ts in _union_cases+_literal_cases for t in ts
}, key=repr)

@pytest.mark.parametrize("t", _other_cases_ts)
def test_other_cases(t: typing.Any) -> None:
    assert can_validate(t), f"Should be able to validate {t}"
    assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
    str(can_validate(t))
    assert_recorded_type(t)

_alias_cases_ts = sorted({
    t for _, ts in _alias_cases for t in ts
}, key=repr)

@pytest.mark.parametrize("t", _alias_cases_ts)
def test_alias_cases(t: typing.Any) -> None:
    with validation_aliases(**_validation_aliases):
        assert can_validate(t), f"Should be able to validate {t}"
        assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
        str(can_validate(t))
        assert_recorded_type(t)

_typed_dict_cases_ts = sorted(_typed_dict_cases.keys(), key=repr)

@pytest.mark.parametrize("t", _typed_dict_cases_ts)
def test_typed_dict_cases(t: typing.Any) -> None:
    with validation_aliases(**_validation_aliases):
        assert can_validate(t), f"Should be able to validate {t}"
        assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
        str(can_validate(t))
        assert_recorded_type(t)

_user_class_cases_ts = sorted({
    t for _, ts in _user_class_cases for t in typing.cast(typing.Any, ts)
}, key=repr)

@pytest.mark.parametrize("t", _user_class_cases_ts)
def test_user_class_cases(t: typing.Any) -> None:
    assert can_validate(t), f"Should be able to validate {t}"
    assert can_validate(typing.Optional[t]), f"Should be able to validate {typing.Optional[t]}"
    str(can_validate(t))
    assert_recorded_type(t)

def test_numpy_array() -> None:
    # pylint: disable = import-outside-toplevel
    import numpy as np
    import numpy.typing as npt
    assert can_validate(npt.NDArray[np.uint8])
    assert can_validate(npt.NDArray[typing.Union[np.uint8, np.float32]])
    assert can_validate(npt.NDArray[typing.Union[typing.Any, np.float32]])
    assert can_validate(npt.NDArray[typing.Any])
    assert can_validate(npt.NDArray[
        typing.Union[
            np.float32,
            typing.Union[
                np.uint16,
                typing.Union[np.int8,typing.Any]
            ]
        ]
    ])

def test_typevar() -> None:
    T = typing.TypeVar("T")
    assert can_validate(T)
    IntT = typing.TypeVar("IntT", bound=int)
    assert can_validate(IntT)
    IntStrSeqT = typing.TypeVar("IntStrSeqT", bound=typing.Sequence[typing.Union[int,str]])
    assert can_validate(IntStrSeqT)
