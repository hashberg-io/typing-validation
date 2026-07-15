# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Tests for the surface around ``validate``: the boolean form, the expression
forms, and the properties the interpreter's shape is supposed to buy.
"""

import sys
from typing import Any, Iterable, Iterator

import pytest

from typing_validation import (
    UnsupportedTypeError,
    ValidationError,
    is_valid,
    validate,
    validated,
    validated_iter,
)


class TestValidate:

    def test_returns_true_so_it_can_be_asserted(self) -> None:
        # The True return exists so validation can be compiled out under -O.
        assert validate(1, int) is True

    def test_raises_a_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            validate("a", int)

    def test_the_error_carries_the_value_and_the_type(self) -> None:
        with pytest.raises(ValidationError) as info:
            validate("a", int)
        assert info.value.val == "a"
        assert info.value.t is int


class TestIsValid:

    def test_returns_a_boolean(self) -> None:
        assert is_valid(1, int) is True
        assert is_valid("a", int) is False

    def test_does_not_swallow_unsupported_types(self) -> None:
        # An unsupported type is not an invalid value, and must not be reported
        # as False. v1 crashed here with AttributeError, because it assumed
        # every TypeError it caught carried a failure.
        with pytest.raises(UnsupportedTypeError):
            is_valid(1, "JSON")


class TestValidated:

    def test_returns_the_value(self) -> None:
        val = [1, 2]
        assert validated(val, list[int]) is val

    def test_raises_on_an_invalid_value(self) -> None:
        with pytest.raises(ValidationError):
            validated(["a"], list[int])


class TestValidatedIter:

    def test_validates_items_as_they_are_yielded(self) -> None:
        assert list(validated_iter(iter([1, 2]), Iterator[int])) == [1, 2]

    def test_raises_at_the_offending_item_rather_than_up_front(self) -> None:
        # The whole point: the items cannot be checked eagerly without consuming
        # the iterator, so they are checked on the way past.
        it = validated_iter(iter([1, "a", 2]), Iterator[int])
        assert next(iter(it)) == 1
        with pytest.raises(ValidationError):
            list(it)

    def test_does_not_consume_the_iterator_up_front(self) -> None:
        source = iter([1, 2, 3])
        validated_iter(source, Iterator[int])
        assert list(source) == [1, 2, 3]

    def test_rejects_a_value_that_is_not_of_the_origin(self) -> None:
        with pytest.raises(ValidationError):
            validated_iter([1, 2], Iterator[int])

    def test_rejects_a_type_that_is_not_iterable(self) -> None:
        with pytest.raises(UnsupportedTypeError):
            validated_iter([1], int)

    def test_passes_an_unparametrised_iterable_through(self) -> None:
        val = [1, "a"]
        assert validated_iter(val, Iterable) is val


type Nested = int | list[Nested]
type NestedStr = str | list[NestedStr]


class TestDeeplyNestedValues:
    """
    The work stack exists for this, and for nothing else.

    What threatens the call stack is the nesting depth of the *value*, not of the
    type: ``list[list[...]]`` is a shallow type, and a list nested thousands deep
    is a legal value for it. A recursive walker would raise ``RecursionError``,
    which is neither a validation failure nor an honest error.
    """

    DEPTH = 20_000

    def _nested(self, innermost: Any) -> Any:
        val = innermost
        for _ in range(self.DEPTH):
            val = [val]
        return val

    def test_a_deeply_nested_valid_value(self) -> None:
        assert self.DEPTH > sys.getrecursionlimit()
        assert validate(self._nested(1), Nested) is True

    def test_a_deeply_nested_invalid_value(self) -> None:
        with pytest.raises(ValidationError):
            validate(self._nested("a"), Nested)

    def test_a_deeply_nested_value_through_a_recursive_alias(self) -> None:
        assert validate(self._nested("a"), NestedStr) is True


class TestUnionsAreUnitsOfSuccess:
    """
    A union member attempt succeeds or fails as a whole.

    Given ``list[int] | list[str]`` and ``[1, "a"]``, the ``1`` validating
    against ``int`` must not settle the union: the attempt is not finished, and
    it will fail on the ``"a"``. A flat work stack has no notion of "this
    attempt", so one had to be added.
    """

    def test_a_partial_member_match_does_not_settle_the_union(self) -> None:
        with pytest.raises(ValidationError):
            validate([1, "a"], list[int] | list[str])

    def test_a_later_member_is_still_tried_after_an_early_failure(self) -> None:
        assert validate(["a", "b"], list[int] | list[str]) is True

    def test_a_failed_attempt_leaves_nothing_behind(self) -> None:
        # Purity is what makes sequential attempts sound.
        assert validate({"a": "b"}, dict[str, int] | dict[str, str]) is True

    def test_nested_unions_each_keep_their_own_attempt(self) -> None:
        t = list[list[int] | str] | str
        assert validate([[1], "a"], t) is True
        assert validate("a", t) is True
        with pytest.raises(ValidationError):
            validate([[1], 2], t)

    def test_a_union_of_plain_classes_takes_the_isinstance_path(self) -> None:
        # No flag, no sequence, no attempts: one isinstance against __args__.
        assert validate(None, int | None) is True
        assert validate(1, int | str | None) is True
        with pytest.raises(ValidationError):
            validate(1.0, int | str | None)
