"""
    Validation failure tracking functionality.
"""

from __future__ import annotations

import sys
import typing
from typing import Any, Callable, Optional

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

    _val: Any
    _t: Any
    _causes: typing.Tuple["ValidationFailure", ...]
    _is_union: bool

    def __new__(cls: typing.Type[_T],
                val: Any, t: Any,
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
    def val(self) -> Any:
        """ The value involved in the validation failure. """
        return self._val

    @property
    def t(self) -> Any:
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

    def visit(self, fun: Callable[[Any, Any, _Acc], _Acc], acc: _Acc) -> None:
        """
            Performs a pre-order visit of the validation failure tree:

            1. applies ``fun(self.val, self.t, acc)`` to the failure,
            2. saves the return value as ``new_acc``
            3. recurses on all causes using ``new_acc``.

            Example usage to pretty-print the validation failure tree using `rich <https://github.com/willmcgugan/rich>`_:

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


            :param fun: the function that will be called on each element of the failure tree during the visit
            :type fun: :py:obj:`~typing.Callable`
            :param acc: the initial value for the accumulator
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

def get_validation_failure(err: TypeError) -> Optional[ValidationFailure]:
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
        :type err: :py:obj:`TypeError`

    """
    if not isinstance(err, TypeError):
        raise TypeError(f"Expected TypeError, found {type(err)}")
    if not hasattr(err, "validation_failure"):
        return None
    validation_failure = getattr(err, "validation_failure")
    if not isinstance(validation_failure, ValidationFailure):
        return None
    return validation_failure

def latest_validation_failure() -> Optional[ValidationFailure]:
    """
        Programmatic access to the validation failure tree for the latest validation call.
        Uses :py:obj:`sys.last_value`, so it must be called immediately after the error occurred.

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
