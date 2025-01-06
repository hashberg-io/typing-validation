# pylint: disable = missing-docstring, expression-not-assigned

import sys
import typing
import pytest

if sys.version_info[1] >= 10:
    from types import UnionType
else:
    UnionType = None

from typing_validation import inspect_type, validation_aliases
from typing_validation.inspector import _typing_equiv
from typing_validation.validation import _pseudotypes_dict

from .test_00_validate import (
    _test_cases,
    _union_cases,
    _literal_cases,
    _alias_cases,
    _typed_dict_cases,
    _user_class_cases,
    _validation_aliases,
)


def assert_recorded_type(t: typing.Any) -> None:
    _t = inspect_type(t).recorded_type
    if t is type(None):
        assert None is _t
    elif (
        hasattr(t, "__origin__")
        and hasattr(t, "__args__")
        and t.__module__ == "typing"
    ):
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


_valid_cases_ts = sorted(
    {t for _, ts in _test_cases for t in ts}
    | {
        _pseudotypes_dict[t]
        for _, ts in _test_cases
        for t in ts
        if t in _pseudotypes_dict
    }
    | {typing.Any},
    key=repr,
)


@pytest.mark.parametrize("t", _valid_cases_ts)
def test_valid_cases(t: typing.Any) -> None:
    # ts = ts+[_pseudotypes_dict[t] for t in ts if t in _pseudotypes_dict]
    assert inspect_type(t), f"Should be able to validate {t}"
    assert inspect_type(
        typing.Optional[t]
    ), f"Should be able to validate {typing.Optional[t]}"
    str(inspect_type(t))
    assert_recorded_type(t)


_other_cases_ts = sorted(
    {t for _, ts in _union_cases + _literal_cases for t in ts}, key=repr
)


@pytest.mark.parametrize("t", _other_cases_ts)
def test_other_cases(t: typing.Any) -> None:
    assert inspect_type(t), f"Should be able to validate {t}"
    assert inspect_type(
        typing.Optional[t]
    ), f"Should be able to validate {typing.Optional[t]}"
    str(inspect_type(t))
    assert_recorded_type(t)


_alias_cases_ts = sorted({t for _, ts in _alias_cases for t in ts}, key=repr)


@pytest.mark.parametrize("t", _alias_cases_ts)
def test_alias_cases(t: typing.Any) -> None:
    with validation_aliases(**_validation_aliases):
        assert inspect_type(t), f"Should be able to validate {t}"
        assert inspect_type(
            typing.Optional[t]
        ), f"Should be able to validate {typing.Optional[t]}"
        str(inspect_type(t))
        assert_recorded_type(t)


_typed_dict_cases_ts = sorted(_typed_dict_cases.keys(), key=repr)


@pytest.mark.parametrize("t", _typed_dict_cases_ts)
def test_typed_dict_cases(t: typing.Any) -> None:
    with validation_aliases(**_validation_aliases):
        assert inspect_type(t), f"Should be able to validate {t}"
        assert inspect_type(
            typing.Optional[t]
        ), f"Should be able to validate {typing.Optional[t]}"
        str(inspect_type(t))
        assert_recorded_type(t)


_user_class_cases_ts = sorted(
    {t for _, ts in _user_class_cases for t in typing.cast(typing.Any, ts)},
    key=repr,
)


@pytest.mark.parametrize("t", _user_class_cases_ts)
def test_user_class_cases(t: typing.Any) -> None:
    assert inspect_type(t), f"Should be able to validate {t}"
    assert inspect_type(
        typing.Optional[t]
    ), f"Should be able to validate {typing.Optional[t]}"
    str(inspect_type(t))
    assert_recorded_type(t)


def test_numpy_array() -> None:
    # pylint: disable = import-outside-toplevel
    import numpy as np
    import numpy.typing as npt

    assert inspect_type(npt.NDArray[np.uint8])
    assert inspect_type(npt.NDArray[typing.Union[np.uint8, np.float32]])
    assert inspect_type(npt.NDArray[typing.Union[typing.Any, np.float32]])
    assert inspect_type(npt.NDArray[typing.Any])
    assert inspect_type(
        npt.NDArray[
            typing.Union[
                np.float32,
                typing.Union[np.uint16, typing.Union[np.int8, typing.Any]],
            ]
        ]
    )


def test_typevar() -> None:
    T = typing.TypeVar("T")
    assert inspect_type(T)
    IntT = typing.TypeVar("IntT", bound=int)
    assert inspect_type(IntT)
    IntStrSeqT = typing.TypeVar(
        "IntStrSeqT", bound=typing.Sequence[typing.Union[int, str]]
    )
    assert inspect_type(IntStrSeqT)


def test_subtype() -> None:
    assert inspect_type(type)
    assert inspect_type(typing.Type)
    assert inspect_type(typing.Type[int])
    assert inspect_type(typing.Type[typing.Union[int, str]])
    assert inspect_type(typing.Type[typing.Any])
    assert inspect_type(typing.Type[typing.Union[typing.Any, str, int]])


_union_cases_ts = sorted({t for _, ts in _union_cases for t in ts}, key=repr)


@pytest.mark.parametrize("t", _union_cases_ts)
def test_union_type_cases(t: typing.Any) -> None:
    if UnionType is not None:
        members = t.__args__
        if not members:
            return
        u = members[0]
        for t in members[1:]:
            u |= t
        assert inspect_type(u)
