"""
    Type validation function.
"""

import collections
import collections.abc as collections_abc
import sys
import typing
from typing import Any, Optional, Union

from .validation_failure import ValidationFailure

if sys.version_info[1] >= 8:
    from typing import Literal
else:
    from typing_extensions import Literal

# constant for the type of None
_NoneType = type(None)

# basic types
_basic_types = frozenset({bool, int, float, complex, bytes, bytearray, memoryview, str, range, slice})

# collection types (parametric on item type)
_collection_pseudotypes_dict = {
    typing.Collection: collections_abc.Collection,
    typing.AbstractSet: collections_abc.Set,
    typing.MutableSet: collections_abc.MutableSet,
    typing.Sequence: collections_abc.Sequence,
    typing.MutableSequence: collections_abc.MutableSequence,
    typing.Deque: collections.deque,
    typing.List: list,
    typing.Set: set,
    typing.FrozenSet: frozenset,
}
_collection_pseudotypes = frozenset(_collection_pseudotypes_dict.keys())|frozenset(_collection_pseudotypes_dict.values())
_collection_origins = frozenset(_collection_pseudotypes_dict.values())

# types that could might be validated as collections (parametric on item type)
_maybe_collection_pseudotypes_dict = {
    typing.Iterable: collections_abc.Iterable,
    typing.Container: collections_abc.Container,
}
_maybe_collection_pseudotypes = frozenset(_maybe_collection_pseudotypes_dict.keys())|frozenset(_maybe_collection_pseudotypes_dict.values())
_maybe_collection_origins = frozenset(_maybe_collection_pseudotypes_dict.values())

# mapping types (parametric on both key type and value type)
_mapping_pseudotypes_dict = {
    typing.Mapping: collections_abc.Mapping,
    typing.MutableMapping: collections_abc.MutableMapping,
    typing.Dict: dict,
    typing.DefaultDict: collections.defaultdict,
}
_mapping_pseudotypes = frozenset(_mapping_pseudotypes_dict.keys())|frozenset(_mapping_pseudotypes_dict.values())
_mapping_origins = frozenset(_mapping_pseudotypes_dict.values())

# tuple and namedtuples
_tuple_pseudotypes = frozenset({typing.Tuple, tuple, typing.NamedTuple, collections.namedtuple})
_tuple_origins = frozenset({tuple, collections.namedtuple})

# other types
_other_pseudotypes_dict = {
    typing.Iterator: collections_abc.Iterator,
    typing.Hashable: collections_abc.Hashable,
    typing.Sized: collections_abc.Sized,
    typing.ByteString: collections_abc.ByteString,
}
_other_pseudotypes = frozenset(_other_pseudotypes_dict.keys())|frozenset(_other_pseudotypes_dict.values())
_other_origins = frozenset(_other_pseudotypes_dict.values())

# all types together
_pseudotypes_dict: typing.Mapping[Any, Any] = {
    **_collection_pseudotypes_dict,
    **_maybe_collection_pseudotypes_dict,
    **_mapping_pseudotypes_dict,
    **_other_pseudotypes_dict
}
_pseudotypes = (_collection_pseudotypes|_maybe_collection_pseudotypes|_mapping_pseudotypes|_tuple_pseudotypes|_other_pseudotypes)
_origins = (_collection_origins|_maybe_collection_origins|_mapping_origins|_tuple_origins|_other_origins)

def _type_error(val: Any, t: Any, *causes: TypeError, is_union: bool = False) -> TypeError:
    """
        Type error arising from `val` not being an instance of type `t`.
        If other type errors are passed as causes, their error messages are indented and included.
        A `validation_failure` attribute of type ValidationFailure is set for the error,
        including full information about the chain of validation failures.
    """
    _causes: typing.Tuple[ValidationFailure, ...] = tuple(
        getattr(error, "validation_failure") for error in causes
        if hasattr(error, "validation_failure")
    )
    assert all(isinstance(cause, ValidationFailure) for cause in _causes)
    validation_failure = ValidationFailure(val, t, *_causes, is_union=is_union)
    error = TypeError(str(validation_failure))
    setattr(error, "validation_failure", validation_failure)
    return error

def _missing_args_msg(t: Any) -> str:
    """ Error message for missing `__args__` attribute on a type `t`. """
    return f"For type {repr(t)}, expected '__args__' attribute." # pragma: nocover

def _wrong_args_num_msg(t: Any, num_args: int) -> str:
    """ Error message for incorrect number of `__args__` on a type `t`. """
    return f"For type {repr(t)}, expected '__args__' to be tuple with {num_args} elements." # pragma: nocover

def _validate_type(val: Any, t: type) -> None:
    """ Basic validation using `isinstance` """
    if not isinstance(val, t):
        raise _type_error(val, t)

def _validate_collection(val: Any, t: Any) -> None:
    """ Parametric collection validation (i.e. recursive validation of all items). """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(t.__args__, tuple) and len(t.__args__) == 1, _wrong_args_num_msg(t, 1)
    item_t = t.__args__[0]
    item_error: Optional[TypeError] = None
    for item in val:
        try:
            validate(item, item_t)
        except TypeError as e:
            item_error = e
            break
    if item_error:
        raise _type_error(val, t, item_error)

def _validate_mapping(val: Any, t: Any) -> None:
    """ Parametric mapping validation (i.e. recursive validation of all keys and values). """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(t.__args__, tuple) and len(t.__args__) == 2, _wrong_args_num_msg(t, 2)
    key_t, value_t = t.__args__
    item_error: Optional[TypeError] = None
    for key, value in val.items():
        try:
            validate(key, key_t)
            validate(value, value_t)
        except TypeError as e:
            item_error = e
            break
    if item_error:
        raise _type_error(val, t, item_error)

def _validate_tuple(val: Any, t: Any) -> None:
    """
        Parametric tuple validation (i.e. recursive validation of all items).
        Two cases:

        - variadic tuple types: arbitrary number of items, all of same type
        - fixed-length tuple types: fixed number of items, each with its individual type
    """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(t.__args__, tuple), f"For type {repr(t)}, expected '__args__' to be a tuple."
    item_error: Optional[TypeError] = None
    if ... in t.__args__: # variadic tuple
        assert len(t.__args__) == 2, _wrong_args_num_msg(t, 2)
        item_t = t.__args__[0]
        for item in val:
            try:
                validate(item, item_t)
            except TypeError as e:
                item_error = e
                break
    else: # fixed-length tuple
        if len(val) != len(t.__args__):
            raise _type_error(val, t)
        for item_t, item in zip(t.__args__, val):
            try:
                validate(item, item_t)
            except TypeError as e:
                item_error = e
                break
    if item_error:
        raise _type_error(val, t, item_error)

def _validate_union(val: Any, t: Any) -> None:
    """
        Union type validation. Each type `u` listed in the union type `t` is checked:

        - if `val` is an instance of `t`, returns immediately without error
        - otherwise, moves to the next `u`

        If `val` is not an instance of any of the types listed in the union, type error is raised.
    """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(t.__args__, tuple), f"For type {repr(t)}, expected '__args__' to be a tuple."
    if not t.__args__:
        return
    member_errors: typing.List[TypeError] = []
    for member_t in t.__args__:
        try:
            validate(val, member_t)
            return
        except TypeError as e:
            member_errors.append(e)
    raise _type_error(val, t, *member_errors, is_union=True)

def _validate_literal(val: Any, t: Any) -> None:
    """
        Literal type validation.
    """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(t.__args__, tuple), f"For type {repr(t)}, expected '__args__' to be a tuple."
    if val not in t.__args__:
        raise _type_error(val, t)

def validate(val: Any, t: Any) -> None:
    """
        Performs runtime type-checking for the value `val` against type `t`.
        Raises `TypeError` if `val` is not of type `t`.
        Raises `ValueError` if validation for type `t` is not supported.
        Raises `AssertionError` if things go unexpectedly wrong with `__args__` for parametric types.

        For structured types, the error message keeps track of the chain of validation failures, e.g.

        ```py
        Python 3.9.7
        >>> from typing import *
        >>> from typing_validation import validate
        >>> validate([[0, 1, 2], {"hi": 0}], list[Union[Collection[int], dict[str, str]]])
        TypeError: For type list[typing.Union[typing.Collection[int], dict[str, str]]],
        invalid value: [[0, 1, 2], {'hi': 0}]
          For type typing.Union[typing.Collection[int], dict[str, str]], invalid value: {'hi': 0}
            Detailed failures for member type typing.Collection[int]:
              For type <class 'int'>, invalid value: 'hi'
            Detailed failures for member type dict[str, str]:
              For type <class 'str'>, invalid value: 0
        ```
    """
    # pylint: disable = too-many-return-statements, too-many-branches
    if t in _basic_types:
        # speed things up for the likely most common case
        _validate_type(val, t)
        return
    if t is None or t is _NoneType:
        if val is not None:
            raise _type_error(val, t)
        return
    if t in _pseudotypes:
        _validate_type(val, t)
        return
    if t is Any:
        return
    if hasattr(t, "__origin__"): # parametric types
        if t.__origin__ is Union:
            _validate_union(val, t)
            return
        if t.__origin__ is Literal:
            _validate_literal(val, t)
            return
        if t.__origin__ in _origins:
            _validate_type(val, t.__origin__)
        if t.__origin__ in _collection_origins:
            _validate_collection(val, t)
            return
        if t.__origin__ in _mapping_origins:
            _validate_mapping(val, t)
            return
        if t.__origin__ == tuple:
            _validate_tuple(val, t)
            return
        if t.__origin__ in _maybe_collection_origins and isinstance(val, typing.Collection):
            _validate_collection(val, t)
            return
    # The `isinstance(t, type)` case goes after the `hasattr(t, "__origin__")` case:
    # e.g. `isinstance(list[int], type)` in 3.10, but we want to validate `list[int]`
    # as a parametric type, not merely as `list` (which is what `_validate_type` does).
    if isinstance(t, type):
        _validate_type(val, t)
        return
    raise ValueError(f"Unsupported validation for type {repr(t)}") # pragma: nocover
