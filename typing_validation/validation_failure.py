"""
    Validation failure tracking functionality.
"""

from __future__ import annotations

import sys
import typing
from typing import Any, Mapping, Optional, Type, TypeVar

if sys.version_info[1] >= 8:
    from typing import Protocol
else:
    from typing_extensions import Protocol

if sys.version_info[1] >= 9:
    from collections.abc import Sequence
else:
    from typing import Sequence

if sys.version_info[1] >= 11:
    from typing import Self
else:
    from typing_extensions import Self


def _indent_lines(lines: Sequence[str], level: int = 1) -> list[str]:
    """Indent all given blocks of text."""
    if any("\n" in line for line in lines):
        lines = [l for line in lines for l in line.split("\n")]
    ind = " " * 2 * level
    return [ind + line for line in lines]


def _type_str(t: Any) -> str:
    if isinstance(t, type):
        return t.__name__
    return str(t)


Acc = typing.TypeVar("Acc")
"""
    Type variable for the accumulator in :meth:`ValidationFailure.visit`.
"""


class FailureTreeVisitor(Protocol[Acc]):
    """
    Structural type for visitor functions that can be passed to
    :meth:`ValidationFailure.visit`.
    """

    def __call__(self, val: Any, t: Any, acc: Acc) -> Acc:
        """
        See :meth:`ValidationFailure.visit` for usage.
        """


class ValidationFailure:
    """
    Generic validation failures.
    """

    _val: Any
    _t: Any
    _causes: typing.Tuple[ValidationFailure, ...]
    _type_aliases: dict[str, Any]

    def __new__(
        cls,
        val: Any,
        t: Any,
        *causes: ValidationFailure,
        type_aliases: Optional[Mapping[str, Any]] = None,
    ) -> Self:
        instance = super().__new__(cls)
        instance._val = val
        instance._t = t
        instance._causes = causes
        instance._type_aliases = (
            {**type_aliases} if type_aliases is not None else {}
        )
        return instance

    @property
    def val(self) -> Any:
        """The value involved in the validation failure."""
        return self._val

    @property
    def t(self) -> Any:
        """The type involved in the validation failure."""
        return self._t

    @property
    def causes(self) -> typing.Tuple[ValidationFailure, ...]:
        r"""
        Validation failure that in turn caused this failure (if any).

        :rtype: :obj:`~typing.Tuple`\ [:class:`ValidationFailure`, ...]
        """
        return self._causes

    @property
    def type_aliases(self) -> Mapping[str, Any]:
        r"""
        The type aliases that were set at the time of validation.
        """
        return self._type_aliases

    def visit(self, fun: FailureTreeVisitor[Acc], acc: Acc) -> None:
        r"""
        Performs a pre-order visit of the validation failure tree:

        1. applies ``fun(self.val, self.t, acc)`` to the failure,
        2. saves the return value as ``new_acc``
        3. recurses on all causes using ``new_acc``.

        For example, this can be used to implement pretty-prenting of validation failures (see :meth:`ValidationFailure.rich_print`):

        >>> import rich
        >>> from rich.tree import Tree
        >>> from rich.text import Text
        >>> from typing import Any, Collection, Union
        >>> from typing_validation import validate, latest_validation_failure
        >>> validate([[0, 1, 2], {"hi": 0}], list[Union[Collection[int], dict[str, str]]])
        TypeError: ...
        >>> failure_tree = Tree("Failure tree")
        >>> def tree_builder(val: Any, t: Any, tree_tip: Tree) -> Tree:
        ...     label = Text(f"({repr(t)}, {repr(val)})")
        ...     tree_tip.add(label) # see https://rich.readthedocs.io/en/latest/tree.html
        ...     return tree_tip
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


        :param fun: the function that will be called on each element of the failure tree during the visit
        :type fun: :obj:`~typing.Callable`\ [[:obj:`~typing.Any`, :obj:`~typing.Any`, ``Acc``], ``Acc``]
        :param acc: the initial value for the accumulator
        :type acc: any type ``Acc``
        """
        new_acc = fun(self.val, self.t, acc)
        for cause in self.causes:
            cause.visit(fun, new_acc)

    def rich_print(self) -> None:
        r"""
        Pretty-prints the validation failure tree using `rich <https://github.com/willmcgugan/rich>`_:

        >>> from typing import Union, Collection
        >>> from typing_validation import validate, latest_validation_failure
        >>> validate([[0, 1, 2], {"hi": 0}], list[Union[Collection[int], dict[str, str]]])
        TypeError: ...
        >>> latest_validation_failure().rich_print()
        Failure tree
        └── (list[typing.Union[typing.Collection[int], dict[str, str]]], [[0, 1, 2], {'hi': 0}])
            └── (typing.Union[typing.Collection[int], dict[str, str]], {'hi': 0})
                ├── (typing.Collection[int], {'hi': 0})
                │   └── (<class 'int'>, 'hi')
                └── (dict[str, str], {'hi': 0})
                    └── (<class 'str'>, 0)

        Raises :obj:`ModuleNotFoundError` if `rich <https://github.com/willmcgugan/rich>`_ is not installed.
        """
        # pylint: disable = import-outside-toplevel
        import rich
        from rich.tree import Tree
        from rich.text import Text

        failure_tree = Tree("Failure tree")

        def tree_builder(val: Any, t: Any, acc: Tree) -> Tree:
            label = Text(f"({repr(t)}, {repr(val)})")
            return acc.add(
                label
            )  # see https://rich.readthedocs.io/en/latest/tree.html

        self.visit(tree_builder, failure_tree)
        rich.print(failure_tree)

    def __str__(self) -> str:
        return "\n".join(self._str_lines(top_level=True))

    def __repr__(self) -> str:
        causes_str = ""
        if self.causes:
            causes_str = ", " + ", ".join(repr(cause) for cause in self.causes)
        return f"{type(self).__name__}({repr(self.val)}, {repr(self.t)}{causes_str})"

    def _str_type_descr(self, type_quals: tuple[str, ...] = ()) -> str:
        descr = (
            "type alias"
            if isinstance(self.t, str)
            else "type variable" if isinstance(self.t, TypeVar) else "type"
        )
        if type_quals:
            descr = " ".join(type_quals) + " " + descr
        return descr

    def _str_main_msg(self, type_quals: tuple[str, ...] = ()) -> str:
        return f"For {self._str_type_descr(type_quals)} {repr(self.t)}, invalid value: {repr(self.val)}"

    def _str_header_lines(self, top_level: bool) -> list[str]:
        if top_level:
            lines = [
                "Runtime validation error raised by validate(val, t), "
                "details below."
            ]
        else:
            lines = []
        if top_level and self.type_aliases:
            lines.append("Validation type aliases:")
            lines.append("{")
            for alias, aliased_t in self.type_aliases.items():
                lines.append(f"    '{alias}': {repr(aliased_t)}")
            lines.append("}")
        return lines

    def _str_causes_lines(self) -> list[str]:
        return [
            line
            for cause in self.causes
            for line in _indent_lines(cause._str_lines(top_level=False))
        ]

    def _str_lines(
        self, *, top_level: bool, type_quals: tuple[str, ...] = ()
    ) -> list[str]:
        # pylint: disable = too-many-branches
        lines = self._str_header_lines(top_level)
        lines.append(self._str_main_msg(type_quals))
        lines.extend(self._str_causes_lines())
        return lines


class UnionValidationFailure(ValidationFailure):
    """
    Validation failures arising from union types.
    """

    def __new__(
        cls,
        val: Any,
        t: Any,
        *causes: ValidationFailure,
        type_aliases: Optional[Mapping[str, Any]] = None,
    ) -> Self:
        instance = super().__new__(
            cls, val, t, *causes, type_aliases=type_aliases
        )
        assert all(cause.val is val for cause in causes)
        return instance

    def _str_type_descr(self, type_quals: tuple[str, ...] = ()) -> str:
        if not type_quals or type_quals[-1] != "union":
            type_quals += ("union",)
        return super()._str_type_descr(type_quals)

    def _str_causes_lines(self) -> list[str]:
        return [
            line
            for cause in self.causes
            for line in _indent_lines(
                cause._str_lines(top_level=False, type_quals=("member",))
            )
        ]


class ValidationFailureAtIdx(ValidationFailure):
    """
    Validation failures arising at a given index of a sequence.
    """

    _idx: int
    _ordered: bool

    def __new__(
        cls,
        val: Any,
        t: Any,
        idx_cause: ValidationFailure,
        idx: int,
        *,
        ordered: bool = True,
        type_aliases: Optional[Mapping[str, Any]] = None,
    ) -> Self:
        # pylint: disable = too-many-arguments
        if ordered:
            assert isinstance(val, Sequence)
        assert idx in range(len(val))
        instance = super().__new__(
            cls, val, t, idx_cause, type_aliases=type_aliases
        )
        instance._idx = idx
        instance._ordered = ordered
        return instance

    @property
    def idx(self) -> int:
        """
        The of the collection item at which this failure arose.
        """
        return self._idx

    @property
    def ordered(self) -> bool:
        """
        Whether the collection is ordered.
        If not, the item :attr:`idx` might not be stable.
        """
        return self._ordered

    def _str_main_msg(self, type_quals: tuple[str, ...] = ()) -> str:
        return (
            f"For {self._str_type_descr(type_quals)} {repr(self.t)}, "
            f"invalid value at idx: {self.idx}"
        )


class ValidationFailureAtKey(ValidationFailure):
    """
    Validation failures arising at a given key of a mapping.
    """

    _key: Any

    def __new__(
        cls,
        val: Any,
        t: Any,
        key_cause: ValidationFailure,
        key: Any,
        *,
        type_aliases: Optional[Mapping[str, Any]] = None,
    ) -> Self:
        # pylint: disable = too-many-arguments
        assert isinstance(val, Mapping)
        assert key in val
        instance = super().__new__(
            cls, val, t, key_cause, type_aliases=type_aliases
        )
        instance._key = key
        return instance

    @property
    def key(self) -> Any:
        """
        The key of the outer sequence at which this failure arose.
        """
        return self._key

    def _str_main_msg(self, type_quals: tuple[str, ...] = ()) -> str:
        return (
            f"For {self._str_type_descr(type_quals)} {repr(self.t)}, "
            f"invalid value at key: {self.key!r}"
        )


class MissingKeysValidationFailure(ValidationFailure):
    """
    Validation failures arising because of missing required keys
    in a mapping.
    """

    _missing_keys: tuple[Any, ...]

    def __new__(
        cls,
        val: Any,
        t: Any,
        missing_keys: Sequence[Any],
        *,
        type_aliases: Optional[Mapping[str, Any]] = None,
    ) -> Self:
        assert isinstance(val, Mapping)
        assert len(missing_keys) >= 0
        assert all(k not in val for k in missing_keys)
        instance = super().__new__(cls, val, t, type_aliases=type_aliases)
        instance._missing_keys = tuple(missing_keys)
        return instance

    @property
    def missing_keys(self) -> tuple[Any, ...]:
        """
        The required key(s) missing from the mapping.
        """
        return self._missing_keys

    def _str_main_msg(self, type_quals: tuple[str, ...] = ()) -> str:
        missing_keys = self.missing_keys
        if len(missing_keys) == 1:
            keys_repr = f"key: {missing_keys[0]!r}"
        else:
            keys_repr = f"keys: {missing_keys!r}"
        return (
            f"For {self._str_type_descr(type_quals)} {repr(self.t)}, "
            f"missing required {keys_repr}"
        )


class InvalidNumpyDTypeValidationFailure(ValidationFailure):
    """
    Validation failures arising because of invalid NumPy dtype.
    """

    def __new__(
        cls,
        val: Any,
        t: Any,
        *,
        type_aliases: Optional[Mapping[str, Any]] = None,
    ) -> Self:
        import numpy as np  # pylint: disable = import-outside-toplevel

        assert isinstance(val, np.ndarray)
        instance = super().__new__(cls, val, t, type_aliases=type_aliases)
        return instance

    def _str_main_msg(self, type_quals: tuple[str, ...] = ()) -> str:
        return (
            f"For {self._str_type_descr(type_quals)} {repr(self.t)}, "
            f"invalid array dtype {self.val.dtype}"
        )


class TypeVarBoundValidationFailure(ValidationFailure):
    """
    Validation failures arising from the bound of a type variable.
    """

    def __new__(
        cls,
        val: Any,
        t: Any,
        bound_cause: ValidationFailure,
        *,
        type_aliases: Optional[Mapping[str, Any]] = None,
    ) -> Self:
        # pylint: disable = too-many-arguments
        instance = super().__new__(
            cls, val, t, bound_cause, type_aliases=type_aliases
        )
        return instance

    def _str_main_msg(self, type_quals: tuple[str, ...] = ()) -> str:
        return (
            f"For {self._str_type_descr(type_quals)} {self.t!r}, "
            f"value is not valid for upper bound: {self.val!r}"
        )


class SubtypeValidationFailure(ValidationFailure):
    """
    Validation failures arising from ``validate(s, Type[t])`` when ``s`` is not
    a subtype of ``t``.
    """

    def __new__(
        cls,
        s: Any,
        t: Any,
        *,
        type_aliases: Optional[Mapping[str, Any]] = None,
    ) -> Self:
        # pylint: disable = too-many-arguments
        instance = super().__new__(cls, s, Type[t], type_aliases=type_aliases)
        return instance

    def _str_main_msg(self, type_quals: tuple[str, ...] = ()) -> str:
        t = self.t
        bound_t = t.__args__[0]
        return (
            f"For {self._str_type_descr(type_quals)} {t!r}, "
            f"type bound is not a supertype of value: {self.val!r}"
        )


def get_validation_failure(err: TypeError) -> ValidationFailure:
    """
    Programmatic access to the validation failure tree for the latest validation call.

    >>> from typing_validation import validate, get_validation_failure
    >>> try:
    ...     validate([[0, 1], [1, 2], [2, "hi"]], list[list[int]])
    ... except TypeError as err:
    ...     validation_failure = get_validation_failure(err)
    ...
    >>> validation_failure
    ValidationFailure([[0, 1], [1, 2], [2, 'hi']], list[list[int]],
        ValidationFailure([2, 'hi'], list[int],
            ValidationFailure('hi', <class 'int'>)))

    :param err: type error raised by :func:`~typing_validation.validation.validate`
    :type err: :obj:`TypeError`

    Raises :obj:`TypeError` if the given error ``err`` is a :obj:`TypeError`.
    Raises :obj:`ValueError` if no validation failure data is available (when ``err`` is not a validation error raised by this library).
    """
    if not isinstance(err, TypeError):
        raise TypeError(f"Expected TypeError, found {type(err)}")
    if not hasattr(err, "validation_failure"):
        raise ValueError("TypeError given is not a validation error.")
    validation_failure = getattr(err, "validation_failure")
    if not isinstance(validation_failure, ValidationFailure):
        raise ValueError("TypeError given is not a validation error.")
    return validation_failure


def latest_validation_failure() -> Optional[ValidationFailure]:
    """
    Programmatic access to the validation failure tree for the latest validation call.
    Uses :obj:`sys.last_value`, so it must be called immediately after the error occurred.

    >>> from typing_validation import validate, latest_validation_failure
    >>> validate([[0, 1], [1, 2], [2, "hi"]], list[list[int]])
    TypeError: ...
    >>> latest_validation_failure()
    ValidationFailure([[0, 1], [1, 2], [2, 'hi']], list[list[int]],
        ValidationFailure([2, 'hi'], list[int],
            ValidationFailure('hi', <class 'int'>)))

    This validation failure information is also set by
    ``is_valid`` in case of failed validation,
    even though no error is raised.
    """
    type_err: Optional[TypeError] = None
    try:
        err = sys.last_value  # pylint: disable = no-member
        if isinstance(err, TypeError):
            type_err = err
    except AttributeError:
        pass
    latest_validation_failure = _set_latest_validation_failure(None)
    if type_err is not None:
        return get_validation_failure(type_err)
    return latest_validation_failure


_latest_validation_failure: Optional[ValidationFailure] = None


def _set_latest_validation_failure(
    failure: Optional[ValidationFailure],
) -> Optional[ValidationFailure]:
    """
    Sets a new value for ``_latest_validation_failure`` and returns
    the previous value.
    """
    global _latest_validation_failure  # pylint: disable = global-statement
    prev_failure = _latest_validation_failure
    _latest_validation_failure = failure
    return prev_failure
