"""
    Runtime typing validation.
"""

import collections
import collections.abc as collections_abc
import sys
import typing

if sys.version_info[1] >= 8:
    from typing import Literal
else:
    from typing_extensions import Literal

# constant for the type of None
_NoneType = type(None)

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
_pseudotypes_dict: typing.Mapping[typing.Any, typing.Any] = {
    **_collection_pseudotypes_dict,
    **_maybe_collection_pseudotypes_dict,
    **_mapping_pseudotypes_dict,
    **_other_pseudotypes_dict
}
_pseudotypes = (_collection_pseudotypes|_maybe_collection_pseudotypes|_mapping_pseudotypes|_tuple_pseudotypes|_other_pseudotypes)
_origins = (_collection_origins|_maybe_collection_origins|_mapping_origins|_tuple_origins|_other_origins)

def _indent(msg: str) -> str:
    """ Indent a block of text (possibly with newlines) """
    ind = " "*2
    return ind+msg.replace("\n", "\n"+ind)

_Acc = typing.TypeVar("_Acc")
_T = typing.TypeVar("_T", bound="ValidationFailure")

class ValidationFailure:
    """
        Simple container class for validation failures.
    """

    _val: typing.Any
    _t: typing.Any
    _causes: typing.Tuple["ValidationFailure", ...]
    _is_union: bool

    def __new__(cls: typing.Type[_T],
                val: typing.Any, t: typing.Any,
                *causes: "ValidationFailure",
                is_union: bool = False) -> _T:
        instance: _T = super().__new__(cls)
        instance._val = val
        instance._t = t
        instance._causes = causes
        instance._is_union = is_union
        if is_union:
            assert all(cause.val == val for cause in causes)
        return instance

    @property
    def val(self) -> typing.Any:
        """ The value involved in the validation failure. """
        return self._val

    @property
    def t(self) -> typing.Any:
        """ The type involved in the validation failure. """
        return self._t

    @property
    def causes(self) -> typing.Tuple["ValidationFailure", ...]:
        """ Validation failure that in turn caused this failure (if any). """
        return self._causes

    @property
    def is_union(self) -> bool:
        """ Whether this validation failure concerns a union type. """
        return self._is_union

    def visit(self, fun: typing.Callable[[typing.Any, typing.Any, _Acc], _Acc], acc: _Acc) -> None:
        """
            Performs a pre-order visit of the validation failure tree:

            1. applies `fun(self.val, self.t, acc)` to the failure,
            2. saves the return value as `new_acc`
            3. recurses on all causes using `new_acc`.

            Example usage to pretty-print the validation failure tree using [rich](https://github.com/willmcgugan/rich):

            ```py
            >>> import rich
            >>> from typing import Union, Collection
            >>> from typing_validation import validate, latest_validation_failure
            >>> validate([[0, 1, 2], {"hi": 0}], list[Union[Collection[int], dict[str, str]]])
            TypeError: ...
            >>> failure_tree = rich.tree.Tree("Failure tree")
            >>> def tree_builder(val, t, tree_tip) -> None:
            ...     label = rich.text.Text(f"({repr(t)}, {repr(val)})")
            ...     return tree_tip.add(label) # see https://rich.readthedocs.io/en/latest/tree.html
            ...
            >>> latest_validation_failure().visit(tree_builder, failure_tree)
            >>> rich.print(failure_tree)
            Failure tree
            └── (list[typing.Union[typing.Collection[int], dict[str, str]]], [[0, 1, 2], {'hi': 0}])
                └── (typing.Union[typing.Collection[int], dict[str, str]], {'hi': 0})
                    ├── (typing.Collection[int], {'hi': 0})
                    │   └── (<class 'int'>, 'hi')
                    └── (dict[str, str], {'hi': 0})
                        └── (<class 'str'>, 0)
            ```
        """
        new_acc = fun(self.val, self.t, acc)
        for cause in self.causes:
            cause.visit(fun, new_acc)

    def __str__(self) -> str:
        msg = f"For type {repr(self.t)}, invalid value: {repr(self.val)}"
        if self._is_union:
            for cause in (cause for cause in self.causes if cause.causes):
                msg += "\n"+_indent(f"Detailed failures for member type {repr(cause.t)}:")
                for sub_cause in cause.causes:
                    msg += "\n"+_indent(_indent(str(sub_cause)))
        else:
            for cause in self.causes:
                msg += "\n"+_indent(str(cause))
        return msg

    def __repr__(self) -> str:
        causes_str = ""
        if self.causes:
            causes_str = ", "+", ".join(repr(cause) for cause in self.causes)
        is_union_str = ""
        if self._is_union:
            is_union_str = ", is_union=True"
        return f"ValidationFailure({repr(self.val)}, {repr(self.t)}{causes_str}{is_union_str})"

def _type_error(val: typing.Any, t: typing.Any, *causes: TypeError, is_union: bool = False) -> TypeError:
    """
        Type error arising from `val` not being an instance of type `t`.
        If other type errors are passed as causes, their error messages are indented and included.
        A `validation_failure` attribute of type `ValidationFailure` is set for the error,
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

def _missing_args_msg(t: typing.Any) -> str:
    """ Error message for missing `__args__` attribute on a type `t`. """
    return f"For type {repr(t)}, expected '__args__' attribute." # pragma: nocover

def _wrong_args_num_msg(t: typing.Any, num_args: int) -> str:
    """ Error message for incorrect number of `__args__` on a type `t`. """
    return f"For type {repr(t)}, expected '__args__' to be tuple with {num_args} elements." # pragma: nocover

def _validate_type(val: typing.Any, t: type) -> None:
    """ Basic validation using `isinstance` """
    if not isinstance(val, t):
        raise _type_error(val, t)

def _validate_collection(val: typing.Any, t: typing.Any) -> None:
    """ Parametric collection validation (i.e. recursive validation of all items). """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(t.__args__, tuple) and len(t.__args__) == 1, _wrong_args_num_msg(t, 1)
    item_t = t.__args__[0]
    item_error: typing.Optional[TypeError] = None
    for item in val:
        try:
            validate(item, item_t)
        except TypeError as e:
            item_error = e
            break
    if item_error:
        raise _type_error(val, t, item_error)

def _validate_mapping(val: typing.Any, t: typing.Any) -> None:
    """ Parametric mapping validation (i.e. recursive validation of all keys and values). """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(t.__args__, tuple) and len(t.__args__) == 2, _wrong_args_num_msg(t, 2)
    key_t, value_t = t.__args__
    item_error: typing.Optional[TypeError] = None
    for key, value in val.items():
        try:
            validate(key, key_t)
            validate(value, value_t)
        except TypeError as e:
            item_error = e
            break
    if item_error:
        raise _type_error(val, t, item_error)

def _validate_tuple(val: typing.Any, t: typing.Any) -> None:
    """
        Parametric tuple validation (i.e. recursive validation of all items).
        Two cases:

        - variadic tuple types: arbitrary number of items, all of same type
        - fixed-length tuple types: fixed number of items, each with its individual type
    """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(t.__args__, tuple), f"For type {repr(t)}, expected '__args__' to be a tuple."
    item_error: typing.Optional[TypeError] = None
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

def _validate_union(val: typing.Any, t: typing.Any) -> None:
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

def _validate_literal(val: typing.Any, t: typing.Any) -> None:
    """
        Literal type validation.
    """
    assert hasattr(t, "__args__"), _missing_args_msg(t)
    assert isinstance(t.__args__, tuple), f"For type {repr(t)}, expected '__args__' to be a tuple."
    if val not in t.__args__:
        raise _type_error(val, t)

def _validate(val: typing.Any, t: typing.Any) -> None:
    """
        Selects the appropriate validation code based on the type.
    """
    # pylint: disable = too-many-return-statements, too-many-branches
    if t is typing.Any:
        return
    if t is None or t is _NoneType:
        if val is not None:
            raise _type_error(val, t)
        return
    if t in _pseudotypes:
        _validate_type(val, t)
        return
    if hasattr(t, "__origin__"): # parametric types
        if t.__origin__ is typing.Union:
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

_validation_failure: typing.Optional[ValidationFailure] = None

def latest_validation_failure() -> typing.Optional[ValidationFailure]:
    """
        Programmatic access to the validation failure tree for the latest validation.
        This is `None` if the latest call to `validate` succeeded without error,
        or if the error was not a validation error (i.e. not a `TypeError`).

        ```py
        >>> from typing_validation import validate, latest_validation_failure
        >>> validate([[0, 1], [1, 2], [2, "hi"]], list[list[int]])
        TypeError: ...
        >>> latest_validation_failure()
        ValidationFailure([[0, 1], [1, 2], [2, 'hi']], list[list[int]],
            ValidationFailure([2, 'hi'], list[int],
                ValidationFailure('hi', <class 'int'>)))
        ```
    """
    return _validation_failure

def validate(val: typing.Any, t: typing.Any) -> None:
    """
        Performs runtime type-checking for the value `val` against type `t`.
        Raises `TypeError` if:

        - `val` is not of type `t`
        - validation for type `t` is not supported

        In cases, such as typed collections/mappings, where items are recursively
        validated, collection exceptions are raised from item exceptions, keeping
        track of the chain of validation failure.
    """
    global _validation_failure # pylint: disable=global-statement
    _validation_failure = None
    try:
        _validate(val, t)
    except TypeError as e:
        if hasattr(e, "validation_failure"):
            _validation_failure = getattr(e, "validation_failure")
            assert isinstance(_validation_failure, ValidationFailure)
        raise e
