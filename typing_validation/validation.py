"""
    Core type validation functionality.
"""

from __future__ import annotations

from contextlib import contextmanager
import collections
import collections.abc as collections_abc
import sys
import typing
from typing import Any, ForwardRef, Optional, Union

from .validation_failure import ValidationFailure

if sys.version_info[1] >= 8:
    from typing import Protocol
else:
    from typing_extensions import Protocol

if sys.version_info[1] >= 11:
    from typing import Literal
else:
    from typing_extensions import Literal

if sys.version_info[1] >= 9:
    from keyword import iskeyword, issoftkeyword
else:
    from keyword import iskeyword
    def issoftkeyword(s: str) -> bool:
        r""" Dummy implementation for issoftkeyword in Python 3.7 and 3.8. """
        return s == "_"

if sys.version_info[1] >= 9:
    TypeConstructorArgs = Union[
        typing.Tuple[Literal["none"], None],
        typing.Tuple[Literal["any"], None],
        typing.Tuple[Literal["type"], type],
        typing.Tuple[Literal["type"], typing.Tuple[type, Literal["tuple"], Optional[int]]],
        typing.Tuple[Literal["type"], typing.Tuple[type, Literal["mapping"], None]],
        typing.Tuple[Literal["type"], typing.Tuple[type, Literal["collection"], None]],
        typing.Tuple[Literal["literal"], typing.Tuple[Any, ...]],
        typing.Tuple[Literal["collection"], None],
        typing.Tuple[Literal["mapping"], None],
        typing.Tuple[Literal["union"], int],
        typing.Tuple[Literal["tuple"], Optional[int]],
        typing.Tuple[Literal["alias"], str],
        typing.Tuple[Literal["unsupported"], Any],
    ]
else:
    TypeConstructorArgs = typing.Tuple[str, Any]

_validation_aliases: typing.Dict[str, Any] = {}
r"""
    Current context of type aliases, used to resolve forward references to type aliases in :func:`validate`.
"""

@contextmanager
def validation_aliases(**aliases: Any) -> collections_abc.Iterator[None]:
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

class UnsupportedType(type):
    r"""
        Wrapper for an unsupported type encountered by a :class:`TypeInspector` instance during validation.
    """

    def __class_getitem__(mcs, wrapped_type: Any) -> "UnsupportedType":
        wrapper = type.__new__(mcs, f"{mcs.__name__}[{wrapped_type}]", tuple(), {})
        wrapper._wrapped_type = wrapped_type
        return wrapper

    _wrapped_type: Any

    @property
    def wrapped_type(cls) -> Any:
        r""" The underlying type. """
        return cls._wrapped_type

class TypeInspector:
    r"""
        Class used to record the structure of a type during a call to :func:`can_validate`.
    """

    _recorded_constructors: typing.List[TypeConstructorArgs]
    _unsupported_types: typing.List[Any]
    _pending_generic_type_constr: Optional[TypeConstructorArgs]

    __slots__ = ("__weakref__", "_recorded_constructors", "_unsupported_types", "_pending_generic_type_constr")

    def __new__(cls) -> "TypeInspector":
        instance = super().__new__(cls)
        instance._recorded_constructors = []
        instance._unsupported_types = []
        instance._pending_generic_type_constr = None
        return instance

    @property
    def recorded_type(self) -> Any:
        r""" The type recorded by this type inspector during validation. """
        t, idx = self._recorded_type(0)
        assert idx == len(self._recorded_constructors)-1, f"The following recorded types have not been included: {self._recorded_constructors[idx+1:]}"
        return t

    @property
    def unsupported_types(self) -> typing.Tuple[Any, ...]:
        r""" The sequence of unsupported types encountered during validation. """
        return tuple(self._unsupported_types)

    def _recorded_type(self, idx: int) -> typing.Tuple[Any, int]:
        # pylint: disable = too-many-return-statements, too-many-branches
        param: Any
        tag, param = self._recorded_constructors[idx]
        if tag == "unsupported":
            return UnsupportedType[param], idx # type: ignore[index]
        if tag == "none":
            return None, idx
        if tag == "any":
            return Any, idx
        if tag == "alias":
            return param, idx
        if tag == "literal":
            assert isinstance(param, tuple)
            return Literal.__getitem__(Literal, *param), idx # pylint: disable = unnecessary-dunder-call
        if tag == "union":
            assert isinstance(param, int)
            member_ts: typing.List[Any] = []
            for _ in range(param):
                member_t, idx = self._recorded_type(idx+1)
                member_ts.append(member_t)
            return typing.Union.__getitem__(tuple(member_ts)), idx
        pending_type = None
        if tag == "type":
            if isinstance(param, type):
                return param, idx
            pending_type, tag, param = param
        if tag == "collection":
            item_t, idx = self._recorded_type(idx+1)
            t = pending_type[item_t] if pending_type is not None else typing.Collection[item_t] # type: ignore[valid-type]
            return t, idx
        if tag == "mapping":
            key_t, idx = self._recorded_type(idx+1)
            value_t, idx = self._recorded_type(idx+1)
            t = pending_type[key_t, value_t] if pending_type is not None else typing.Mapping[key_t, value_t] # type: ignore[valid-type]
            return t, idx
        if tag == "tuple":
            if param is None:
                item_t, idx = self._recorded_type(idx+1)
                t = pending_type[item_t,...] if pending_type is not None else typing.Tuple[item_t,...]
                return t, idx
            assert isinstance(param, int)
            item_ts: typing.List[Any] = []
            for _ in range(param):
                item_t, idx = self._recorded_type(idx+1)
                item_ts.append(item_t)
            if not item_ts:
                item_ts = [tuple()]
            t = pending_type.__class_getitem__(tuple(item_ts)) if pending_type is not None else typing.Tuple.__getitem__(tuple(item_ts))
            return t, idx
        assert False, f"Invalid type constructor tag: {repr(tag)}"

    def _append_constructor_args(self, args: TypeConstructorArgs) -> None:
        pending_generic_type_constr = self._pending_generic_type_constr
        if pending_generic_type_constr is None:
            self._recorded_constructors.append(args)
            return
        pending_tag, pending_param = pending_generic_type_constr
        args_tag, args_param = args
        assert pending_tag == "type" and isinstance(pending_param, type)
        assert args_tag in ("tuple", "mapping", "collection"), f"Found unexpected tag '{args_tag}' with type constructor {pending_generic_type_constr} pending."
        if sys.version_info[1] >= 9:
            self._recorded_constructors.append(typing.cast(TypeConstructorArgs, ("type", (pending_param, args_tag, args_param))))
        else:
            self._recorded_constructors.append(("type", (pending_param, args_tag, args_param)))
        self._pending_generic_type_constr = None

    def _record_none(self) -> None:
        self._append_constructor_args(("none", None))

    def _record_any(self) -> None:
        self._append_constructor_args(("any", None))

    def _record_type(self, t: type) -> None:
        self._append_constructor_args(("type", t))

    def _record_pending_type_generic(self, t: type) -> None:
        assert self._pending_generic_type_constr is None
        self._pending_generic_type_constr = ("type", t)

    def _record_collection(self, item_t: Any) -> None:
        self._append_constructor_args(("collection", None))

    def _record_mapping(self, key_t: Any, value_t: Any) -> None:
        self._append_constructor_args(("mapping", None))

    def _record_union(self, *member_ts: Any) -> None:
        self._append_constructor_args(("union", len(member_ts)))

    def _record_variadic_tuple(self, item_t: Any) -> None:
        self._append_constructor_args(("tuple", None))

    def _record_fixed_tuple(self, *item_ts: Any) -> None:
        self._append_constructor_args(("tuple", len(item_ts)))

    def _record_literal(self, *literals: Any) -> None:
        self._append_constructor_args(("literal", literals))

    def _record_alias(self, t_alias: str) -> None:
        self._append_constructor_args(("alias", t_alias))

    def _record_unsupported_type(self, unsupported_t: Any) -> None:
        self._pending_generic_type_constr = None
        self._unsupported_types.append(unsupported_t)
        self._append_constructor_args(("unsupported", unsupported_t))

    def __bool__(self) -> bool:
        return not self._unsupported_types

    def __repr__(self) -> str:
        # addr = "0x"+f"{id(self):x}"
        header = f"The following type can{'' if self else 'not'} be validated against:"
        return header+"\n"+"\n".join(self._repr()[0])

    def _repr(self, idx: int = 0, level: int = 0) -> typing.Tuple[typing.List[str], int]:
        # pylint: disable = too-many-return-statements, too-many-branches, too-many-statements
        indent = "    "*level
        param: Any
        lines: typing.List[str]
        tag, param = self._recorded_constructors[idx]
        if tag == "unsupported":
            return [indent+"UnsupportedType[", indent+"    "+str(param), indent+"]"], idx
        if tag == "none":
            return [indent+"NoneType"], idx
        if tag == "any":
            return [indent+"Any"], idx
        if tag == "alias":
            return [indent+f"{repr(param)}"], idx
        if tag == "literal":
            assert isinstance(param, tuple)
            return [indent+f"Literal[{', '.join(repr(p) for p in param)}]"], idx
        if tag == "union":
            assert isinstance(param, int)
            lines = [indent+"Union["]
            for _ in range(param):
                member_lines, idx = self._repr(idx+1, level+1)
                member_lines[-1] += ","
                lines.extend(member_lines)
            assert len(lines) > 1, "Cannot take a union of no types."
            lines.append(indent+"]")
            return lines, idx
        pending_type = None
        if tag == "type":
            if isinstance(param, type):
                return [indent+param.__name__], idx
            pending_type, tag, param = param
        if tag == "collection":
            item_lines, idx = self._repr(idx+1, level+1)
            if pending_type is not None:
                lines = [indent+f"{pending_type.__name__}[", *item_lines, indent+"]"]
            else:
                lines = [indent+"Collection[", *item_lines, indent+"]"]
            return lines, idx
        if tag == "mapping":
            key_lines, idx = self._repr(idx+1, level+1)
            key_lines[-1] += ","
            value_lines, idx = self._repr(idx+1, level+1)
            if pending_type is not None:
                lines = [indent+f"{pending_type.__name__}[", *key_lines, *value_lines, indent+"]"]
            else:
                lines = [indent+"Mapping[", *key_lines, *value_lines, indent+"]"]
            return lines, idx
        if tag == "tuple":
            if param is None:
                item_lines, idx = self._repr(idx+1, level+1)
                if pending_type is not None:
                    lines = [indent+f"{pending_type.__name__}[", *item_lines, indent+"]"]
                else:
                    lines = [indent+"Tuple[", *item_lines, indent+"]"]
                return lines, idx
            assert isinstance(param, int)
            lines = [indent+f"{pending_type.__name__}[" if pending_type is not None else indent+"Tuple["]
            for _ in range(param):
                item_lines, idx = self._repr(idx+1, level+1)
                item_lines[-1] += ","
                lines.extend(item_lines)
            if len(lines) == 1:
                lines.append("tuple()")
            lines.append(indent+"]")
            return lines, idx
        assert False, f"Invalid type constructor tag: {repr(tag)}"


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
_pseudotypes = _collection_pseudotypes|_maybe_collection_pseudotypes|_mapping_pseudotypes|_tuple_pseudotypes|_other_pseudotypes
_origins = _collection_origins|_maybe_collection_origins|_mapping_origins|_tuple_origins|_other_origins

def _type_error(val: Any, t: Any, *causes: TypeError, is_union: bool = False) -> TypeError:
    """
        Type error arising from ``val`` not being an instance of type ``t``.

        If other type errors are passed as causes, their error messages are indented and included.
        A :func:`validation_failure` attribute of type ValidationFailure is set for the error,
        including full information about the chain of validation failures.
    """
    _causes: typing.Tuple[ValidationFailure, ...] = tuple(
        getattr(error, "validation_failure") for error in causes
        if hasattr(error, "validation_failure")
    )
    assert all(isinstance(cause, ValidationFailure) for cause in _causes)
    validation_failure = ValidationFailure(val, t, *_causes, is_union=is_union, type_aliases=_validation_aliases)
    error = TypeError(str(validation_failure))
    setattr(error, "validation_failure", validation_failure)
    return error

def _type_alias_error(t_alias: str, nested_error: TypeError) -> TypeError:
    """
        Repackages a validation error as a type alias error.
    """
    assert hasattr(nested_error, "validation_failure"), nested_error
    validation_failure = getattr(nested_error, "validation_failure")
    assert isinstance(validation_failure, ValidationFailure), validation_failure
    validation_failure._t = t_alias
    return nested_error

def _missing_args_msg(t: Any) -> str:
    """ Error message for missing :attr:`__args__` attribute on a type ``t``. """
    return f"For type {repr(t)}, expected '__args__' attribute." # pragma: nocover

def _wrong_args_num_msg(t: Any, num_args: int) -> str:
    """ Error message for incorrect number of :attr:`__args__` on a type ``t``. """
    return f"For type {repr(t)}, expected '__args__' to be tuple with {num_args} elements." # pragma: nocover

def _validate_type(val: Any, t: type) -> None:
    """ Basic validation using :func:`isinstance` """
    if isinstance(val, TypeInspector):
        val._record_type(t)
        return
    if not isinstance(val, t):
        raise _type_error(val, t)

def _validate_collection(val: Any, t: Any) -> None:
    """ Parametric collection validation (i.e. recursive validation of all items). """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(t.__args__, tuple) and len(t.__args__) == 1, _wrong_args_num_msg(t, 1)
    item_t = t.__args__[0]
    if isinstance(val, TypeInspector):
        val._record_collection(item_t)
        validate(val, item_t)
        return
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
    if isinstance(val, TypeInspector):
        val._record_mapping(key_t, value_t)
        validate(val, key_t)
        validate(val, value_t)
        return
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
        if isinstance(val, TypeInspector):
            val._record_variadic_tuple(item_t)
            validate(val, item_t)
            return
        for item in val:
            try:
                validate(item, item_t)
            except TypeError as e:
                item_error = e
                break
    else: # fixed-length tuple
        if isinstance(val, TypeInspector):
            val._record_fixed_tuple(*t.__args__)
            for item_t in t.__args__:
                validate(val, item_t)
            return
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
        Union type validation. Each type ``u`` listed in the union type ``t`` is checked:

        - if ``val`` is an instance of ``t``, returns immediately without error
        - otherwise, moves to the next ``u``

        If ``val`` is not an instance of any of the types listed in the union, type error is raised.
    """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(t.__args__, tuple), f"For type {repr(t)}, expected '__args__' to be a tuple."
    if isinstance(val, TypeInspector):
        val._record_union(*t.__args__)
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
    assert isinstance(t.__args__, tuple), f"For type {repr(t)}, expected '__args__' to be a tuple."
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

def validate(val: Any, t: Any) -> None:
    """
        Performs runtime type-checking for the value ``val`` against type ``t``.

        For structured types, the error message keeps track of the chain of validation failures, e.g.

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

        **Note.** For Python 3.7 and 3.8, use :obj:`~typing.Dict` and :obj:`~typing.List` instead of :obj:`dict` and :obj:`list` for the above examples.

        :param val: the value to be type-checked
        :type val: :obj:`~typing.Any`
        :param t: the type to type-check against
        :type t: :obj:`~typing.Any`
        :raises TypeError: if ``val`` is not of type ``t``
        :raises ValueError: if validation for type ``t`` is not supported
        :raises AssertionError: if things go unexpectedly wrong with :attr:`__args__` for parametric types

    """
    # pylint: disable = too-many-return-statements, too-many-branches, too-many-statements
    unsupported_type_error: Optional[ValueError] = None
    if t in _basic_types:
        # speed things up for the likely most common case
        _validate_type(val, t)
        return
    if t is None or t is _NoneType:
        if isinstance(val, TypeInspector):
            val._record_none()
            return
        if val is not None:
            raise _type_error(val, t)
        return
    if t in _pseudotypes:
        _validate_type(val, t)
        return
    if t is Any:
        if isinstance(val, TypeInspector):
            val._record_any()
            return
        return
    if hasattr(t, "__origin__"): # parametric types
        if t.__origin__ is Union:
            _validate_union(val, t)
            return
        if t.__origin__ is Literal:
            _validate_literal(val, t)
            return
        if t.__origin__ in _origins:
            if isinstance(val, TypeInspector):
                val._record_pending_type_generic(t.__origin__)
            else:
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
    elif isinstance(t, type):
        # The `isinstance(t, type)` case goes after the `hasattr(t, "__origin__")` case:
        # e.g. `isinstance(list[int], type)` in 3.10, but we want to validate `list[int]`
        # as a parametric type, not merely as `list` (which is what `_validate_type` does).
        if Protocol in t.__mro__: # type: ignore[comparison-overlap]
            if hasattr(t, "_is_runtime_protocol") and getattr(t, "_is_runtime_protocol"):
                _validate_type(val, t)
                return
            if isinstance(val, TypeInspector):
                val._record_unsupported_type(t)
                return
            unsupported_type_error = ValueError(f"Unsupported validation for Protocol {repr(t)}, because it is not runtime-checkable.") # pragma: nocover
        else:
            _validate_type(val, t)
            return
    elif isinstance(t, (str, ForwardRef)):
        if isinstance(t, str):
            t_alias: str = t
        else:
            t_alias = t.__forward_arg__
        if t_alias not in _validation_aliases:
            if t_alias.isidentifier() and not iskeyword(t_alias) and not issoftkeyword(t_alias):
                hint = f"Perhaps set it with validation_aliases({t_alias}=...)?"
            else:
                hint = f"Perhaps set it with validation_aliases(**{{'{t_alias}': ...}})?"
            unsupported_type_error = ValueError(f"Type alias '{t_alias}' is not known. {hint}") # pragma: nocover
        else:
            _validate_alias(val, t_alias)
            return
    if isinstance(val, TypeInspector):
        val._record_unsupported_type(t)
        return
    if unsupported_type_error is None:
        unsupported_type_error = ValueError(f"Unsupported validation for type {repr(t)}.") # pragma: nocover
    raise unsupported_type_error

def can_validate(t: Any) -> TypeInspector:
    r"""
        Checks whether validation is supported for the given type ``t``: if not, :func:`validate` will raise :obj:`ValueError`.

        The returned :class:`TypeInspector` instance can be used wherever a boolean is expected, and will indicate whether the type is supported or not:

        >>> from typing import *
        >>> from typing_validation import can_validate
        >>> res = can_validate(tuple[list[str], Union[int, float, Callable[[int], int]]])
        >>> bool(res)
        False

        However, it also records (with minimal added cost) the full structure of the type as the latter was validated, which it then exposes via its
        :attr:`TypeInspector.recorded_type` property:

        >>> res = can_validate(tuple[list[Union[str, int]],...])
        >>> bool(res)
        True
        >>> res.recorded_type
        tuple[list[typing.Union[str, int]], ...]

        Any unsupported subtype encountered during the validation is left in place, wrapped into an :class:`UnsupportedType`:

        >>> can_validate(tuple[list[str], Union[int, float, Callable[[int], int]]])
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
        :raises AssertionError: if things go unexpectedly wrong with :attr:`__args__` for parametric types
    """
    inspector = TypeInspector()
    validate(inspector, t)
    return inspector
