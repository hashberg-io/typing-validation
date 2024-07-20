"""
    Core type validation functionality.
"""

from __future__ import annotations

from contextlib import contextmanager
import collections
import collections.abc as collections_abc
from keyword import iskeyword
import sys
import typing
from typing import (
    Any,
    ForwardRef,
    Hashable,
    Optional,
    TypeVar,
    Union,
    get_type_hints,
)

from .validation_failure import (
    InvalidNumpyDTypeValidationFailure,
    SubtypeValidationFailure,
    TypeVarBoundValidationFailure,
    ValidationFailureAtIdx,
    ValidationFailureAtKey,
    MissingKeysValidationFailure,
    UnionValidationFailure,
    ValidationFailure,
    _set_latest_validation_failure,
)
from .inspector import TypeInspector

if sys.version_info[1] >= 8:
    from typing import Literal, Protocol
else:
    from typing_extensions import Literal, Protocol

if sys.version_info[1] >= 9:
    from keyword import issoftkeyword
else:

    def issoftkeyword(s: str) -> bool:
        r"""Dummy implementation for issoftkeyword in Python 3.7 and 3.8."""
        return s == "_"


if sys.version_info[1] >= 10:
    from types import NoneType, UnionType
else:
    NoneType = type(None)
    UnionType = None


try:
    import typing_extensions
except ModuleNotFoundError:
    _typing_modules = [typing]
else:
    _typing_modules = [typing, typing_extensions]


_validation_aliases: typing.Dict[str, Any] = {}
r"""
    Current context of type aliases, used to resolve forward references to type aliases in :func:`validate`.
"""


@contextmanager
def validation_aliases(**aliases: Any) -> collections.abc.Iterator[None]:
    r"""
    Sets type aliases that can be used to resolve forward references in :func:`validate`.

    For example, the following snippet validates a value against a recursive type alias for JSON-like objects, using :func:`validation_aliases` to create a
    context where :func:`validate` internally evaluates the forward reference ``"JSON"`` to the type alias ``JSON``:

    >>> JSON = Union[int, float, bool, None, str, list["JSON"], dict[str, "JSON"]]
    >>> with validation_aliases(JSON=JSON):
    >>>     validate([1, 2.2, {"a": ["Hello", None, {"b": True}]}], list["JSON"])

    """
    # pylint: disable = global-statement
    global _validation_aliases
    outer_validation_aliases = _validation_aliases
    _validation_aliases = {**_validation_aliases}
    _validation_aliases.update(aliases)
    try:
        yield
    finally:
        _validation_aliases = outer_validation_aliases


def _get_type_classes(name: str) -> typing.List[typing.Type[Any]]:
    """Get the classes for the specified type from typing and its possible backport modules."""
    return [
        getattr(module, name)
        for module in _typing_modules
        if hasattr(module, name)
    ]

# basic types
_basic_types = frozenset(
    {bool, int, float, complex, bytes, bytearray, memoryview, str, range, slice}
)

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
_collection_pseudotypes = frozenset(
    _collection_pseudotypes_dict.keys()
) | frozenset(_collection_pseudotypes_dict.values())
_collection_origins = frozenset(_collection_pseudotypes_dict.values())

# ordered collection types (parametric on item type)
_ordered_collection_pseudotypes_dict = {
    typing.Sequence: collections_abc.Sequence,
    typing.MutableSequence: collections_abc.MutableSequence,
    typing.Deque: collections.deque,
    typing.List: list,
}
_ordered_collection_pseudotypes = frozenset(
    _ordered_collection_pseudotypes_dict.keys()
) | frozenset(_ordered_collection_pseudotypes_dict.values())
_ordered_collection_origins = frozenset(
    _ordered_collection_pseudotypes_dict.values()
)

# types that might be validated as collections (parametric on item type)
_maybe_collection_pseudotypes_dict = {
    typing.Iterable: collections_abc.Iterable,
    typing.Container: collections_abc.Container,
}
_maybe_collection_pseudotypes = frozenset(
    _maybe_collection_pseudotypes_dict.keys()
) | frozenset(_maybe_collection_pseudotypes_dict.values())
_maybe_collection_origins = frozenset(
    _maybe_collection_pseudotypes_dict.values()
)

# mapping types (parametric on both key type and value type)
_mapping_pseudotypes_dict = {
    typing.Mapping: collections_abc.Mapping,
    typing.MutableMapping: collections_abc.MutableMapping,
    typing.Dict: dict,
    typing.DefaultDict: collections.defaultdict,
}
_mapping_pseudotypes = frozenset(_mapping_pseudotypes_dict.keys()) | frozenset(
    _mapping_pseudotypes_dict.values()
)
_mapping_origins = frozenset(_mapping_pseudotypes_dict.values())

# tuple and namedtuples
_tuple_pseudotypes = frozenset(
    {typing.Tuple, tuple, typing.NamedTuple, collections.namedtuple}
)
_tuple_origins = frozenset({tuple, collections.namedtuple})

# other types
_other_pseudotypes_dict = {
    typing.Iterator: collections_abc.Iterator,
    typing.Hashable: collections_abc.Hashable,
    typing.Sized: collections_abc.Sized,
}
if sys.version_info[1] <= 11:
    _other_pseudotypes_dict[typing.ByteString] = collections_abc.ByteString  # type: ignore
else:
    from collections.abc import Buffer as _collections_abc_Buffer

    _other_pseudotypes_dict[_collections_abc_Buffer] = _collections_abc_Buffer

_other_pseudotypes = frozenset(_other_pseudotypes_dict.keys()) | frozenset(
    _other_pseudotypes_dict.values()
)
_other_origins = frozenset(_other_pseudotypes_dict.values())

_iterator_origins = frozenset(
    [
        typing.Iterator,
        collections_abc.Iterator,
        typing.Iterable,
        collections_abc.Iterable,
    ]
)

# all types together
_pseudotypes_dict: typing.Mapping[Any, Any] = {
    **_collection_pseudotypes_dict,
    **_maybe_collection_pseudotypes_dict,
    **_mapping_pseudotypes_dict,
    **_other_pseudotypes_dict,
}  # used by tests
_pseudotypes = (
    _collection_pseudotypes
    | _maybe_collection_pseudotypes
    | _mapping_pseudotypes
    | _tuple_pseudotypes
    | _other_pseudotypes
)
_origins = (
    _collection_origins
    | _maybe_collection_origins
    | _mapping_origins
    | _tuple_origins
    | _other_origins
)


class UnsupportedTypeError(ValueError):
    """
    Class for errors raised when attempting to validate an unsupported type.

    .. warning::

        Currently extends :obj:`ValueError` for backwards compatibility.
        This will be changed to :obj:`NotImplementedError` in v1.3.0.
    """


def _unsupported_type_error(
    t: Any, explanation: Union[str, None] = None
) -> UnsupportedTypeError:
    """
    Error for unsupported types, with optional explanation.
    """
    msg = "Unsupported validation for type {t!r}."
    if explanation is not None:
        msg += " " + explanation
    return UnsupportedTypeError(msg)


def _type_error(
    val: Any, t: Any, *errors: TypeError, is_union: bool = False
) -> TypeError:
    """
    Type error arising from ``val`` not being an instance of type ``t``.

    If other type errors are passed as causes, their error messages are indented and included.
    A :func:`validation_failure` attribute of type ValidationFailure is set for the error,
    including full information about the chain of validation failures.
    """
    causes: typing.Tuple[ValidationFailure, ...] = tuple(
        getattr(error, "validation_failure")
        for error in errors
        if hasattr(error, "validation_failure")
    )
    assert all(isinstance(cause, ValidationFailure) for cause in causes)
    validation_failure: ValidationFailure
    if is_union:
        validation_failure = UnionValidationFailure(
            val, t, *causes, type_aliases=_validation_aliases
        )
    else:
        validation_failure = ValidationFailure(
            val, t, *causes, type_aliases=_validation_aliases
        )
    error = TypeError(str(validation_failure))
    setattr(error, "validation_failure", validation_failure)
    return error


def _typevar_error(val: Any, t: Any, bound_error: TypeError) -> TypeError:
    assert hasattr(bound_error, "validation_failure"), bound_error
    cause = getattr(bound_error, "validation_failure")
    assert isinstance(cause, ValidationFailure), cause
    validation_failure = TypeVarBoundValidationFailure(val, t, cause)
    error = TypeError(str(validation_failure))
    setattr(error, "validation_failure", validation_failure)
    return error


def _idx_type_error(
    val: Any, t: Any, idx_error: TypeError, *, idx: int, ordered: bool
) -> TypeError:
    assert hasattr(idx_error, "validation_failure"), idx_error
    idx_cause = getattr(idx_error, "validation_failure")
    assert isinstance(idx_cause, ValidationFailure), idx_cause
    validation_failure = ValidationFailureAtIdx(
        val, t, idx_cause, idx=idx, ordered=ordered
    )
    error = TypeError(str(validation_failure))
    setattr(error, "validation_failure", validation_failure)
    return error


def _key_type_error(
    val: Any, t: Any, key_error: TypeError, *, key: Any
) -> TypeError:
    assert hasattr(key_error, "validation_failure"), key_error
    key_cause = getattr(key_error, "validation_failure")
    assert isinstance(key_cause, ValidationFailure), key_cause
    validation_failure = ValidationFailureAtKey(val, t, key_cause, key=key)
    error = TypeError(str(validation_failure))
    setattr(error, "validation_failure", validation_failure)
    return error


def _missing_keys_type_error(val: Any, t: Any, *missing_keys: Any) -> TypeError:
    validation_failure = MissingKeysValidationFailure(val, t, missing_keys)
    error = TypeError(str(validation_failure))
    setattr(error, "validation_failure", validation_failure)
    return error


def _subtype_error(s: Any, t: Any) -> TypeError:
    validation_failure = SubtypeValidationFailure(s, t)
    error = TypeError(str(validation_failure))
    setattr(error, "validation_failure", validation_failure)
    return error


def _type_alias_error(t_alias: str, cause: TypeError) -> TypeError:
    """
    Repackages a validation error as a type alias error.
    """
    assert hasattr(cause, "validation_failure"), cause
    validation_failure = getattr(cause, "validation_failure")
    assert isinstance(validation_failure, ValidationFailure), validation_failure
    validation_failure._t = t_alias
    return cause


def _numpy_dtype_error(val: Any, t: Any) -> TypeError:
    """
    Type error arising from ``val`` not being an instance of NumPy array
    type ``t``, because ``val.dtype`` is not valid.
    """
    validation_failure = InvalidNumpyDTypeValidationFailure(val, t)
    error = TypeError(str(validation_failure))
    setattr(error, "validation_failure", validation_failure)
    return error


def _missing_args_msg(t: Any) -> str:
    """Error message for missing :attr:`__args__` attribute on a type ``t``."""
    return (
        f"For type {repr(t)}, expected '__args__' attribute."  # pragma: nocover
    )


def _wrong_args_num_msg(t: Any, num_args: int) -> str:
    """Error message for incorrect number of :attr:`__args__` on a type ``t``."""
    return f"For type {repr(t)}, expected '__args__' to be tuple with {num_args} elements."  # pragma: nocover


def _validate_type(val: Any, t: type) -> None:
    """Basic validation using :func:`isinstance`"""
    if isinstance(val, TypeInspector):
        val._record_type(t)
        return
    if not isinstance(val, t):
        raise _type_error(val, t)


def _validate_collection(val: Any, t: Any, ordered: bool) -> None:
    """Parametric collection validation (i.e. recursive validation of all items)."""
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert (
        isinstance(t.__args__, tuple) and len(t.__args__) == 1
    ), _wrong_args_num_msg(t, 1)
    item_t = t.__args__[0]
    if isinstance(val, TypeInspector):
        val._record_collection(item_t)
        validate(val, item_t)
        return
    for idx, item in enumerate(val):
        try:
            validate(item, item_t)
        except TypeError as e:
            raise _idx_type_error(val, t, e, idx=idx, ordered=ordered) from None


def _validate_mapping(val: Any, t: Any) -> None:
    """Parametric mapping validation (i.e. recursive validation of all keys and values)."""
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert (
        isinstance(t.__args__, tuple) and len(t.__args__) == 2
    ), _wrong_args_num_msg(t, 2)
    key_t, value_t = t.__args__
    if isinstance(val, TypeInspector):
        val._record_mapping(key_t, value_t)
        validate(val, key_t)
        validate(val, value_t)
        return
    for key, value in val.items():
        try:
            validate(key, key_t)
        except TypeError as e:
            raise _type_error(val, t, e) from None
        try:
            validate(value, value_t)
        except TypeError as e:
            raise _key_type_error(val, t, e, key=key) from None


def _validate_tuple(val: Any, t: Any) -> None:
    """
    Parametric tuple validation (i.e. recursive validation of all items).
    Two cases:

    - variadic tuple types: arbitrary number of items, all of same type
    - fixed-length tuple types: fixed number of items, each with its individual type
    """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(
        t.__args__, tuple
    ), f"For type {repr(t)}, expected '__args__' to be a tuple."
    if ... in t.__args__:  # variadic tuple
        assert len(t.__args__) == 2, _wrong_args_num_msg(t, 2)
        item_t = t.__args__[0]
        if isinstance(val, TypeInspector):
            val._record_variadic_tuple(item_t)
            validate(val, item_t)
            return
        for idx, item in enumerate(val):
            try:
                validate(item, item_t)
            except TypeError as e:
                raise _idx_type_error(
                    val, t, e, idx=idx, ordered=True
                ) from None
    else:  # fixed-length tuple
        if isinstance(val, TypeInspector):
            val._record_fixed_tuple(*t.__args__)
            for item_t in t.__args__:
                validate(val, item_t)
            return
        if len(val) != len(t.__args__):
            raise _type_error(val, t)
        for idx, (item_t, item) in enumerate(zip(t.__args__, val)):
            try:
                validate(item, item_t)
            except TypeError as e:
                raise _idx_type_error(
                    val, t, e, idx=idx, ordered=True
                ) from None


def _validate_union(val: Any, t: Any, *, use_UnionType: bool = False) -> None:
    """
    Union type validation. Each type ``u`` listed in the union type ``t`` is checked:

    - if ``val`` is an instance of ``t``, returns immediately without error
    - otherwise, moves to the next ``u``

    If ``val`` is not an instance of any of the types listed in the union, type error is raised.
    """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(
        t.__args__, tuple
    ), f"For type {repr(t)}, expected '__args__' to be a tuple."
    if isinstance(val, TypeInspector):
        val._record_union(*t.__args__, use_UnionType=use_UnionType)
        for member_t in t.__args__:
            validate(val, member_t)
        return
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
    assert isinstance(
        t.__args__, tuple
    ), f"For type {repr(t)}, expected '__args__' to be a tuple."
    if isinstance(val, TypeInspector):
        val._record_literal(*t.__args__)
        return
    if val not in t.__args__:
        raise _type_error(val, t)


def _validate_alias(val: Any, t_alias: str) -> None:
    r"""
    Validation of type aliases within the context provided by :func:`validation`
    """
    t = _validation_aliases[t_alias]
    if isinstance(val, TypeInspector):
        val._record_alias(t_alias)
        return
    nested_error: Optional[TypeError] = None
    try:
        validate(val, t)
    except TypeError as e:
        nested_error = e
    if nested_error is not None:
        raise _type_alias_error(t_alias, nested_error)


def _is_typed_dict(t: type) -> bool:
    """
    Determines whether a type is a subclass of :class:`TypedDict`.
    """
    return t.__class__ in _get_type_classes('_TypedDictMeta')


def _validate_typed_dict(val: Any, t: type) -> None:
    """
    Validation of :class:`TypedDict` subclasses.
    """
    annotations = get_type_hints(t)
    required_keys: frozenset[str] = getattr(t, "__required_keys__")
    if isinstance(val, TypeInspector):
        val._record_typed_dict(t)
        for k, val_t in annotations.items():
            validate(val, val_t)
        return
    # 1. Validate that `val`` is a mapping with string keys:
    try:
        validate(val, typing.Mapping[str, typing.Any])
    except TypeError as e:
        raise _type_error(val, t, e) from None
    # 2. Validate presence of required keys:
    missing_keys = [k for k in required_keys if k not in val]
    if missing_keys:
        raise _missing_keys_type_error(val, t, *missing_keys)
    # 3. Validate value types:
    for k, v in annotations.items():
        if k in val:
            try:
                validate(val[k], v)
            except TypeError as e:
                raise _key_type_error(val, t, e, key=k) from None


def _validate_user_class(val: Any, t: Any) -> None:
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(
        t.__args__, tuple
    ), f"For type {repr(t)}, expected '__args__' to be a tuple."
    if isinstance(val, TypeInspector):
        if t.__origin__ is type:
            if len(t.__args__) != 1 or not _can_validate_subtype_of(
                t.__args__[0]
            ):
                val._record_unsupported_type(t)
                return
        val._record_pending_type_generic(t.__origin__)
        val._record_user_class(*t.__args__)
        for arg in t.__args__:
            validate(val, arg)
        return
    _validate_type(val, t.__origin__)
    if t.__origin__ is type:
        if len(t.__args__) != 1:
            raise _unsupported_type_error(t)
        _validate_subtype_of(val, t.__args__[0])
        return
    # TODO: Generic type arguments cannot be validated in general,
    #       but in a future release it will be possible for classes to define
    #       a dunder classmethod which can be used to validate type arguments.


def __extract_member_types(u: Any) -> tuple[Any, ...] | None:
    q = collections.deque([u])
    member_types: list[Any] = []
    while q:
        t = q.popleft()
        if t is Any:
            return None
        elif UnionType is not None and isinstance(t, UnionType):
            q.extend(t.__args__)
        elif hasattr(t, "__origin__") and t.__origin__ is Union:
            q.extend(t.__args__)
        else:
            member_types.append(t)
    return tuple(member_types)


def __check_can_validate_subtypes(*subtypes: Any) -> None:
    for s in subtypes:
        if not isinstance(s, type):
            raise ValueError(
                "validate(s, Type[t]) is only supported when 's' is "
                "an instance of 'type' or a union of instances of 'type'.\n"
                f"Found s = {'|'.join(str(s) for s in subtypes)}"
            )


def __check_can_validate_supertypes(*supertypes: Any) -> None:
    for t in supertypes:
        if not isinstance(t, type):
            raise ValueError(
                "validate(s, Type[t]) is only supported when 't' is "
                "an instance of 'type' or a union of instances of 'type'.\n"
                f"Found t = {'|'.join(str(t) for t in supertypes)}"
            )


def _can_validate_subtype_of(t: Any) -> bool:
    try:
        # This is the validation part of _validate_subtype:
        t_member_types = __extract_member_types(t)
        if t_member_types is not None:
            __check_can_validate_supertypes(*t_member_types)
        return True
    except ValueError:
        return False


def _validate_subtype_of(s: Any, t: Any) -> None:
    # 1. Validation:
    __check_can_validate_subtypes(s)
    t_member_types = __extract_member_types(t)
    if t_member_types is None:
        # An Any was found amongst the member types, all good.
        return
    __check_can_validate_supertypes(*t_member_types)
    # 2. Subtype check:
    if not issubclass(s, t_member_types):
        raise _subtype_error(s, t)
    # TODO: improve support for subtype checks.


def _extract_dtypes(t: Any) -> typing.Sequence[Any]:
    if t is Any:
        return [Any]
    if (
        UnionType is not None
        and isinstance(t, UnionType)
        or hasattr(t, "__origin__")
        and t.__origin__ is Union
    ):
        return [
            dtype for member in t.__args__ for dtype in _extract_dtypes(member)
        ]
    import numpy as np  # pylint: disable = import-outside-toplevel

    if hasattr(t, "__origin__"):
        t_origin = t.__origin__
        if t_origin in {
            np.number,
            np.inexact,
            np.floating,
            np.complexfloating,
            np.integer,
            np.signedinteger,
            np.unsignedinteger,
        }:
            if t == t_origin[Any]:
                return [t_origin]
            # TODO: add broader support for np.NBitBase subtypes
    if isinstance(t, type) and issubclass(t, np.generic):
        return [t]
    raise TypeError()


def _validate_numpy_array(val: Any, t: Any) -> None:
    import numpy as np  # pylint: disable = import-outside-toplevel

    if not isinstance(val, TypeInspector):
        _validate_type(val, np.ndarray)
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert len(t.__args__) == 2, _wrong_args_num_msg(t, 2)
    dtype_t_container = t.__args__[1]
    assert hasattr(dtype_t_container, "__args__"), _missing_args_msg(
        dtype_t_container
    )
    assert len(dtype_t_container.__args__) == 1, _wrong_args_num_msg(
        dtype_t_container, 1
    )
    dtype_t = dtype_t_container.__args__[0]
    try:
        dtypes = _extract_dtypes(dtype_t)
    except TypeError:
        if isinstance(val, TypeInspector):
            val._record_unsupported_type(t)
            return
        raise _unsupported_type_error(
            t, f"Unsupported NumPy dtype {dtype_t!r}"
        ) from None
    if isinstance(val, TypeInspector):
        val._record_pending_type_generic(t.__origin__)
        val._record_user_class(*t.__args__)
        for arg in t.__args__:
            validate(val, arg)
        return
    val_dtype = val.dtype
    if any(dtype is Any or np.issubdtype(val_dtype, dtype) for dtype in dtypes):
        return
    raise _numpy_dtype_error(val, t)


def _validate_typevar(val: Any, t: TypeVar) -> None:
    if isinstance(val, TypeInspector):
        val._record_typevar(t)
        pass
    bound = t.__bound__
    if bound is not None:
        try:
            validate(val, bound)
        except TypeError as e:
            raise _typevar_error(val, t, e) from None


# def _validate_callable(val: Any, t: Any) -> None:
#     """
#         Callable validation
#     """
#     assert hasattr(t, "__args__"), _missing_args_msg(t)
#     assert isinstance(t.__args__, tuple), f"For type {repr(t)}, expected '__args__' to be a tuple."
#     if not callable(val):
#         raise _type_error(val, t, is_union=True)
#     if not t.__args__:
#         return
#     exp_params = t.__args__[:-1]
#     exp_ret = t.__args__[-1]
#     sig = inspect.signature(val)
#     empty = sig.empty
#     params = sig.parameters
#     ret = sig.return_annotation
#     positional_only: typing.List[inspect.Parameter] = []
#     positional_or_keyword: typing.Dict[str, inspect.Parameter] = {}
#     var_positional: Optional[inspect.Parameter] = None
#     keyword_only: typing.Dict[str, inspect.Parameter] = {}
#     var_keyword: Optional[inspect.Parameter] = None
#     for param_name, param in params.items():
#         if param.kind == param.POSITIONAL_ONLY:
#             positional_only.append(param)
#         elif param.kind == param.POSITIONAL_OR_KEYWORD:
#             positional_or_keyword[param_name] = param
#         elif param.kind == param.VAR_POSITIONAL:
#             var_positional = param
#         elif param.kind == param.KEYWORD_ONLY:
#             keyword_only[param_name] = param
#         elif param.kind == param.VAR_KEYWORD:
#             var_keyword = param
#     # still work in progress
#     raise _type_error(val, t, is_union=True)


def validate(val: Any, t: Any) -> Literal[True]:
    """
    Performs runtime type-checking for the value ``val`` against type ``t``.
    The function raises :obj:`TypeError` upon failure and returns :obj:`True` upon success.
    The :obj:`True` return value means that :func:`validate` can be gated behind assertions
    and compiled away on optimised execution:

    .. code-block:: python

        assert validate(val, t) # compiled away using -O and -OO

    For structured types, the error message keeps track of the chain of validation failures, e.g.

        >>> from typing import *
        >>> from typing_validation import validate
        >>> validate([[0, 1, 2], {"hi": 0}], list[Union[Collection[int], dict[str, str]]])
        TypeError: Runtime validation error raised by validate(val, t), details below.
        For type list[typing.Union[typing.Collection[int], dict[str, str]]], invalid value at idx: 1
        For union type typing.Union[typing.Collection[int], dict[str, str]], invalid value: {'hi': 0}
            For member type typing.Collection[int], invalid value at idx: 0
            For type <class 'int'>, invalid value: 'hi'
            For member type dict[str, str], invalid value at key: 'hi'
            For type <class 'str'>, invalid value: 0

    **Note.** For Python 3.7 and 3.8, use :obj:`~typing.Dict` and :obj:`~typing.List` instead of :obj:`dict` and :obj:`list` for the above examples.

    :param val: the value to be type-checked
    :type val: :obj:`~typing.Any`
    :param t: the type to type-check against
    :type t: :obj:`~typing.Any`
    :raises TypeError: if ``val`` is not of type ``t``
    :raises UnsupportedTypeError: if validation for type ``t`` is not supported
    :raises AssertionError: if things go unexpectedly wrong with ``__args__`` for parametric types

    """
    # pylint: disable = too-many-return-statements, too-many-branches, too-many-statements
    unsupported_type_error: Optional[UnsupportedTypeError] = None
    if not isinstance(t, Hashable):
        if isinstance(val, TypeInspector):
            val._record_unsupported_type(t)
            return True
        if unsupported_type_error is None:
            unsupported_type_error = _unsupported_type_error(
                t, "Type is not hashable."
            )  # pragma: nocover
        raise unsupported_type_error
    if t is typing.Type:
        # Replace non-generic 'Type' with non-generic 'type':
        t = type
    if t in _basic_types:
        # speed things up for the likely most common case
        _validate_type(val, typing.cast(type, t))
        return True
    if t is None or t is NoneType:
        if isinstance(val, TypeInspector):
            val._record_none()
            return True
        if val is not None:
            raise _type_error(val, t)
        return True
    if t in _pseudotypes:
        _validate_type(val, typing.cast(type, t))
        return True
    if t is Any:
        if isinstance(val, TypeInspector):
            val._record_any()
            return True
        return True
    if isinstance(t, TypeVar):
        _validate_typevar(val, t)
        return True
    if UnionType is not None and isinstance(t, UnionType):
        _validate_union(val, t, use_UnionType=True)
        return True
    if hasattr(t, "__origin__"):  # parametric types
        if t.__origin__ is Union:
            _validate_union(val, t)
            return True
        if t.__origin__ in _get_type_classes('Literal'):
            _validate_literal(val, t)
            return True
        if t.__origin__ in _origins:
            if isinstance(val, TypeInspector):
                val._record_pending_type_generic(t.__origin__)
            else:
                _validate_type(val, t.__origin__)
            if t.__origin__ in _collection_origins:
                ordered = t.__origin__ in _ordered_collection_origins
                _validate_collection(val, t, ordered)
                return True
            if t.__origin__ in _mapping_origins:
                _validate_mapping(val, t)
                return True
            if t.__origin__ == tuple:
                _validate_tuple(val, t)
                return True
            if t.__origin__ in _iterator_origins:
                if isinstance(val, TypeInspector):
                    _validate_collection(val, t, ordered=False)
                # Item type cannot be validated for iterators (use validated_iter)
                return True
            if t.__origin__ in _maybe_collection_origins and isinstance(
                val, typing.Collection
            ):
                _validate_collection(val, t, ordered=False)
                return True
        elif isinstance(t.__origin__, type):
            try:
                import numpy as np  # pylint: disable = import-outside-toplevel

                if issubclass(t.__origin__, np.ndarray):
                    _validate_numpy_array(val, t)
                    return True
            except ModuleNotFoundError:
                pass
            _validate_user_class(val, t)
            return True
    elif isinstance(t, type):
        # The `isinstance(t, type)` case goes after the `hasattr(t, "__origin__")` case:
        # e.g. `isinstance(list[int], type)` in 3.10, but we want to validate `list[int]`
        # as a parametric type, not merely as `list` (which is what `_validate_type` does).
        if Protocol in t.__mro__:  # type: ignore[comparison-overlap]
            if hasattr(t, "_is_runtime_protocol") and getattr(
                t, "_is_runtime_protocol"
            ):
                _validate_type(val, t)
                return True
            if isinstance(val, TypeInspector):
                val._record_unsupported_type(t)
                return True
            unsupported_type_error = _unsupported_type_error(
                t, "Protocol class is not runtime-checkable."
            )  # pragma: nocover
        elif _is_typed_dict(t):
            _validate_typed_dict(val, t)
            return True
        else:
            _validate_type(val, t)
            return True
    elif isinstance(t, (str, ForwardRef)):
        if isinstance(t, str):
            t_alias: str = t
        else:
            t_alias = t.__forward_arg__
        if t_alias not in _validation_aliases:
            if (
                t_alias.isidentifier()
                and not iskeyword(t_alias)
                and not issoftkeyword(t_alias)
            ):
                hint = f"Perhaps set it with validation_aliases({t_alias}=...)?"
            else:
                hint = f"Perhaps set it with validation_aliases(**{{'{t_alias}': ...}})?"
            unsupported_type_error = _unsupported_type_error(
                t_alias, f"Type alias is not known. {hint}"
            )  # pragma: nocover
        else:
            _validate_alias(val, t_alias)
            return True
    if isinstance(val, TypeInspector):
        val._record_unsupported_type(t)
        return True
    if unsupported_type_error is None:
        unsupported_type_error = _unsupported_type_error(t)  # pragma: nocover
    raise unsupported_type_error


def can_validate(t: Any) -> TypeInspector:
    """
    Checks whether validation is supported for the given type ``t``: if not,
    :func:`validate` will raise :obj:`UnsupportedTypeError`.

    .. warning::

        The return type will be changed to :obj:`bool` in v1.3.0.
        To obtain a :class:`TypeInspector` object, please use the newly
        introduced :func:`inspect_type` instead.

    :param t: the type to be checked for validation support
    :type t: :obj:`~typing.Any`

    """
    inspector = TypeInspector()
    validate(inspector, t)
    return inspector


def inspect_type(t: Any) -> TypeInspector:
    r"""
    Returns a :class:`TypeInspector` instance can be used wherever a boolean is
    expected, and will indicate whether the type is supported or not:

    >>> from typing import *
    >>> from typing_validation import inspect_type
    >>> res = inspect_type(tuple[list[str], Union[int, float, Callable[[int], int]]])
    >>> bool(res)
    False

    The instance also records (with minimal added cost) the full structure of
    the type as the latter was validated, which it then exposes via its
    :attr:`TypeInspector.recorded_type` property:

    >>> res = inspect_type(tuple[list[Union[str, int]],...])
    >>> bool(res)
    True
    >>> res.recorded_type
    tuple[list[typing.Union[str, int]], ...]

    Any unsupported subtype encountered during the validation is left in place,
    wrapped into an :class:`UnsupportedType`:

    >>> inspect_type(tuple[list[str], Union[int, float, Callable[[int], int]]])
    The following type cannot be validated against:
    tuple[
        list[
            str
        ],
        Union[
            int,
            float,
            UnsupportedType[
                typing.Callable[[int], int]
            ],
        ],
    ]

    **Note.** For Python 3.7 and 3.8, use :obj:`~typing.Tuple` and :obj:`~typing.List` instead of :obj:`tuple` and :obj:`list` for the above examples.

    :param t: the type to be checked for validation support
    :type t: :obj:`~typing.Any`

    """
    inspector = TypeInspector()
    validate(inspector, t)
    return inspector


T = typing.TypeVar("T")
"""
    Invariant type variable used by the functions :func:`validated`
    and :func:`validated_iter`.
"""


def is_valid(val: T, t: Any) -> bool:
    """
    Performs the same functionality as :func:`validate`, but returning
    :obj:`False` if validation is unsuccessful instead of raising error.

    In case of validation failure, detailed failure information is accessible
    via :func:`~typing_validation.validation_failure.latest_validation_failure`.
    """
    try:
        validate(val, t)
        _set_latest_validation_failure(None)
        return True
    except TypeError as e:
        _set_latest_validation_failure(getattr(e, "validation_failure"))
        return False


def validated(val: T, t: Any) -> T:
    """
    Performs the same functionality as :func:`validate`, but returns ``val``
    if validation is successful.

    Useful when multiple elements must be validated as part of a larger
    expression, e.g. as part of a comprehension:

    .. code-block :: python

        def sortint(*items: int) -> list[int]:
            return sorted(validate(i) for i in items)

    """
    validate(val, t)
    return val


def validated_iter(val: typing.Iterable[T], t: Any) -> typing.Iterable[T]:
    """
    Performs the same functionality as :func:`validated`, but the iterable
    ``var`` is wrapped into an iterator which validates its items prior to
    them being yielded.
    """
    validate(val, t)
    if t in _iterator_origins:
        return val
    if hasattr(t, "__origin__") and t.__origin__ in _iterator_origins:
        assert hasattr(t, "__args__"), _missing_args_msg(t)
        assert (
            isinstance(t.__args__, tuple) and len(t.__args__) == 1
        ), _wrong_args_num_msg(t, 1)
        item_t = t.__args__[0]
        return (validated(item, item_t) for item in val)
    raise ValueError(
        "Argument 't' must be Iterable, Iterator, Iterable[T], or Iterator[T]."
    )
