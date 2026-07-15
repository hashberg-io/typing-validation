# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Errors raised by validation.

The two errors answer different questions — *"I cannot check this"* versus
*"I checked this and it is wrong"* — and they deliberately share no base beyond
:class:`Exception`. A caller must be able to tell them apart, and a test must
never be able to mistake one for the other.
"""

from typing import TYPE_CHECKING, Any, Self, final

if TYPE_CHECKING:
    from .diagnosis import ValidationFailure

__all__ = ("UnsupportedTypeError", "ValidationError")


@final
class UnsupportedTypeError(NotImplementedError):
    """
    Raised when a type is not one that this library knows how to validate
    against.

    Support is all-or-nothing: an unsupported component makes the whole type
    unsupported, so this is raised for ``tuple[int, Callable[[int], int]]`` even
    though the ``int`` component is perfectly checkable.

    This is a :class:`NotImplementedError` rather than a validation failure: the
    value was never in question. Use :func:`~typing_validation.can_validate` to
    ask in advance whether a type can be honoured at all.
    """

    __slots__ = ("_t", "_explanation")

    _t: Any
    """The type that cannot be validated against."""

    _explanation: str | None
    """Additional detail about what is unsupported, and what would fix it."""

    def __new__(cls, t: Any, explanation: str | None = None, /) -> Self:
        """
        :param t: the whole type that cannot be validated against.
        :param explanation: optional additional lines naming the component at
            fault and, where possible, how to gain support for it.
        """
        self: Self = NotImplementedError.__new__(cls, t, explanation)
        self._t = t
        self._explanation = explanation
        return self

    @property
    def t(self) -> Any:
        """The type that cannot be validated against."""
        return self._t

    @property
    def explanation(self) -> str | None:
        """Additional detail about what is unsupported, and what would fix it."""
        return self._explanation

    def __str__(self) -> str:
        msg = f"Unsupported validation for type {self._t!r}."
        if self._explanation is not None:
            msg += "\n" + self._explanation
        return msg


@final
class ValidationError(TypeError):
    """
    Raised when a value is not valid for a type.

    This is a :class:`TypeError` subclass, which is the contract callers have
    relied on since v1. It is a *distinct* subclass so that a test can assert
    the library rejected a value, rather than merely that something somewhere
    raised a :class:`TypeError` — a distinction that hid a real crash in v1 for
    eleven releases.

    The structured explanation hangs off :attr:`~typing_validation.errors.ValidationError.failure`, as a proper attribute
    rather than v1's ``setattr(error, "validation_failure", …)`` smuggling.
    Programmatic access is then an attribute on an exception you have already
    caught, which is what ``get_validation_failure`` existed to provide.
    """

    __slots__ = ("_val", "_t", "_failure")

    _val: Any
    """The value that failed validation."""

    _t: Any
    """The type the value was validated against."""

    _failure: "ValidationFailure | None"
    """The structured explanation, when one was built."""

    def __new__(
        cls, val: Any, t: Any, failure: "ValidationFailure | None" = None, /
    ) -> Self:
        """
        :param val: the value that failed validation.
        :param t: the type it was validated against.
        :param failure: the structured explanation, if one was built.
        """
        self: Self = TypeError.__new__(cls, val, t, failure)
        self._val = val
        self._t = t
        self._failure = failure
        return self

    @property
    def failure(self) -> "ValidationFailure | None":
        """
        The structured explanation of what went wrong, and where.

        :obj:`None` when nothing built one — ``validated_iter`` reports the item
        it stopped at without diagnosing the whole iterable.
        """
        return self._failure

    @property
    def val(self) -> Any:
        """The value that failed validation."""
        return self._val

    @property
    def t(self) -> Any:
        """The type the value was validated against."""
        return self._t

    def __str__(self) -> str:
        if self._failure is not None:
            return str(self._failure)
        return f"For type {self._t!r}, invalid value: {self._val!r}"
