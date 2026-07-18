# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Tests for messages about objects that refuse to describe themselves.

An object whose ``__repr__`` raises is not a curiosity: a class that reprs its
own attributes raises from inside ``__init__`` until the last one is assigned,
which is where a caller validating ``self`` will meet it. If rendering the
failure raises, the traceback the user reads is their own ``__repr__`` and not
the diagnosis, and the message that was supposed to explain the problem has
destroyed the evidence instead.

So every one of these asks the same question: does the message survive, and does
it still say the thing it exists to say.
"""

from typing import Any, Literal

import pytest

from typing_validation import (
    UnsupportedTypeError,
    ValidationError,
    compiled_validator,
    is_valid,
    validate,
    validator,
)
from typing_validation.nodes import node_for


class Hostile:
    """A value that raises from its own ``__repr__``, as the issue reported."""

    def __repr__(self) -> str:
        raise ZeroDivisionError("division by zero")


class HostileKey(Hostile):
    """The same, but usable as a mapping key or a set member."""

    def __hash__(self) -> int:
        return 0


HOSTILE_ARG = HostileKey()
"""
A hostile object appearing *inside* a type form.

A class renders by its ``__name__`` and so cannot misbehave, but the type forms
built out of it render by ``repr``: ``str(list[x])`` and ``str(Literal[x])`` both
repr their arguments. That is how a type, and not merely a value, reaches a
message through an untrusted ``__repr__``.
"""


def _message(val: Any, t: Any, /) -> str:
    with pytest.raises(ValidationError) as info:
        validate(val, t)
    return str(info.value)


class TestValidationIsUnaffected:
    """
    The verdict never depended on the repr, and this pins that down.

    Worth stating separately, because the reported symptom made it look as
    though such objects could not be validated at all.
    """

    def test_a_hostile_value_validates(self) -> None:
        assert validate(Hostile(), Hostile) is True

    def test_a_hostile_value_is_rejected_cleanly(self) -> None:
        assert is_valid(Hostile(), int) is False

    def test_validating_self_before_it_is_built(self) -> None:
        # The case from the issue: __repr__ reads an attribute that __init__ has
        # not assigned yet, and __init__ validates self on the way past.
        class HalfBuilt:
            def __init__(self) -> None:
                assert validate(self, HalfBuilt) is True
                self.x = 1

            def __repr__(self) -> str:
                return f"HalfBuilt({self.x})"

        assert HalfBuilt().x == 1


class TestTheMessageSurvives:

    def test_at_the_root(self) -> None:
        message = _message(Hostile(), int)
        assert "expected int" in message
        assert "Hostile" in message

    def test_inside_a_collection(self) -> None:
        message = _message([Hostile()], list[int])
        assert "value[0]" in message

    def test_as_a_mapping_value(self) -> None:
        message = _message({"a": Hostile()}, dict[str, int])
        assert "value['a']" in message

    def test_as_a_mapping_key(self) -> None:
        message = _message({HostileKey(): 1}, dict[str, int])
        assert "expected str" in message

    def test_as_the_type(self) -> None:
        # `t` is caller-supplied too, and reaches the message through str()
        # rather than repr() — a separate path, and separately guarded.
        message = _message(2, Literal[HOSTILE_ARG])
        assert "__repr__ raised ZeroDivisionError" in message
        assert "got 2" in message

    def test_the_repr_failure_is_named_as_such(self) -> None:
        # Not a blank: a reader who expected a repr is told whose fault it is.
        message = _message(Hostile(), int)
        assert "__repr__ raised ZeroDivisionError" in message

    @pytest.mark.parametrize("mechanism", ["validate", "validator", "compiled"])
    def test_every_mechanism_survives(self, mechanism: str) -> None:
        # Diagnosis is shared, so this is one implementation — which is exactly
        # why it is worth checking that all three actually reach it.
        with pytest.raises(ValidationError) as info:
            if mechanism == "validate":
                validate(Hostile(), int)
            elif mechanism == "validator":
                validator(int)(Hostile())
            else:
                compiled_validator(int)(Hostile())
        assert "expected int" in str(info.value)


class TestReprsOfTheLibrarysOwnObjects:
    """
    The failure tree and the node model repr their subjects too, and a debugger
    printing one of those is in no better a position than a user reading a
    message.
    """

    def test_a_failure_reprs(self) -> None:
        with pytest.raises(ValidationError) as info:
            validate(Hostile(), int)
        assert "ValidationFailure" in repr(info.value.failure)

    def test_a_node_reprs(self) -> None:
        assert "TypeNode" in repr(node_for(list[HOSTILE_ARG]))  # type: ignore[valid-type]

    def test_an_unsupported_type_error_reprs(self) -> None:
        # This one renders the type with repr(), and an unsupported type is the
        # likeliest place for a caller to have passed something exotic.
        with pytest.raises(UnsupportedTypeError) as info:
            validator(list[HOSTILE_ARG])  # type: ignore[valid-type]
        assert "__repr__ raised ZeroDivisionError" in str(info.value)
