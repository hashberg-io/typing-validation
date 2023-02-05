"""
    Validation failure tracking functionality.
"""

from __future__ import annotations

import sys
import typing
from typing import Any, Callable, List, Mapping, Optional

def _indent(msg: str) -> str:
    """ Indent a block of text (possibly with newlines) """
    ind = " "*2
    return ind+msg.replace("\n", "\n"+ind)

def _type_str(t: Any) -> str:
    if isinstance(t, type):
        return t.__name__
    return str(t)

_Acc = typing.TypeVar("_Acc")

class ValidationFailure:
    """
        Simple container class for validation failures.
    """

    _val: Any
    _t: Any
    _causes: typing.Tuple["ValidationFailure", ...]
    _is_union: bool
    _type_aliases: dict[str, Any]

    def __new__(cls,
                val: Any, t: Any,
                *causes: "ValidationFailure",
                is_union: bool = False,
                type_aliases: Optional[Mapping[str, Any]] = None) -> "ValidationFailure":
        instance: ValidationFailure = super().__new__(cls)
        instance._val = val
        instance._t = t
        instance._causes = causes
        instance._is_union = is_union
        instance._type_aliases = {**type_aliases} if type_aliases is not None else {}
        if is_union:
            assert all(cause.val == val for cause in causes)
        return instance

    @property
    def val(self) -> Any:
        """ The value involved in the validation failure. """
        return self._val

    @property
    def t(self) -> Any:
        """ The type involved in the validation failure. """
        return self._t

    @property
    def causes(self) -> typing.Tuple["ValidationFailure", ...]:
        r"""
            Validation failure that in turn caused this failure (if any).

            :rtype: :obj:`~typing.Tyuple`\ [:class:`ValidationFailure`, ...]
        """
        return self._causes

    @property
    def is_union(self) -> bool:
        """ Whether this validation failure concerns a union type. """
        return self._is_union

    @property
    def type_aliases(self) -> Mapping[str, Any]:
        r"""
            The type aliases that were set at the time of validation.
        """
        return self._type_aliases

    def visit(self, fun: Callable[[Any, Any, _Acc], _Acc], acc: _Acc) -> None:
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
        def tree_builder(val: Any, t: Any, tree_tip: Tree) -> Tree:
            label = Text(f"({repr(t)}, {repr(val)})")
            return tree_tip.add(label) # see https://rich.readthedocs.io/en/latest/tree.html
        self.visit(tree_builder, failure_tree)
        rich.print(failure_tree)

    def __str__(self) -> str:
        return self._str(top_level=True)

    def __repr__(self) -> str:
        causes_str = ""
        if self.causes:
            causes_str = ", "+", ".join(repr(cause) for cause in self.causes)
        is_union_str = ""
        if self._is_union:
            is_union_str = ", is_union=True"
        return f"ValidationFailure({repr(self.val)}, {repr(self.t)}{causes_str}{is_union_str})"

    def _str(self, *, top_level: bool) -> str:
        # pylint: disable = too-many-branches
        t = self.t
        type_descr = "type alias" if isinstance(t, str) else "type"
        if self.is_union:
            type_descr = f"union {type_descr}"

        if top_level:
            lines = ["Runtime validation error raised by validate(val, t), details below."]
        else:
            lines = []
        if top_level and self.type_aliases:
            lines.append("Validation type aliases:")
            lines.append("{")
            for alias, aliased_t in self.type_aliases.items():
                lines.append(f"    '{alias}': {repr(aliased_t)}")
            lines.append("}")
        lines.append(f"For {type_descr} {repr(t)}, invalid value: {repr(self.val)}")
        if self._is_union:
            leaf_causes: List[ValidationFailure] = []
            causes_to_expand: List[ValidationFailure] = []
            for cause in self.causes:
                if cause.causes:
                    causes_to_expand.append(cause)
                else:
                    leaf_causes.append(cause)
            if leaf_causes and causes_to_expand:
                leaf_causes_line = f"Not of the following member types: {', '.join(_type_str(cause.t) for cause in leaf_causes)}."
                lines.append(_indent(leaf_causes_line))
            elif leaf_causes:
                leaf_causes_line = f"Not of any member type: {', '.join(_type_str(cause.t) for cause in leaf_causes)}."
                lines.append(_indent(leaf_causes_line))
            elif causes_to_expand:
                pass
            else:
                lines.append("Type union is empty.")
            for cause in causes_to_expand:
                lines.append(_indent(f"Not of member type {repr(cause.t)}, details below:"))
                for sub_cause in cause.causes:
                    lines.append(_indent(_indent(sub_cause._str(top_level=False))))
        else:
            for cause in self.causes:
                lines.append(_indent(cause._str(top_level=False)))
        return "\n".join(lines)

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

    """
    try:
        err = sys.last_value # pylint: disable = no-member
    except AttributeError:
        return None
    if not isinstance(err, TypeError):
        return None
    return get_validation_failure(err)
