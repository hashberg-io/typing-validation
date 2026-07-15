# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Tests for the error hierarchy.

The hierarchy is a contract, not an implementation detail: the test rule of
DESIGN.md §10 — assert :class:`ValidationError`, never :class:`TypeError` — is
only enforceable because the two errors are distinguishable, and the plugin
messages of §7 are only reachable because :class:`UnsupportedTypeError` carries
an explanation.
"""

import pickle

import pytest

from typing_validation import UnsupportedTypeError, ValidationError


class TestUnsupportedTypeError:

    def test_is_not_implemented_error(self) -> None:
        assert issubclass(UnsupportedTypeError, NotImplementedError)

    def test_is_not_a_value_error(self) -> None:
        # v1 extended ValueError and documented this change as coming in 1.3.0.
        assert not issubclass(UnsupportedTypeError, ValueError)

    def test_does_not_share_a_base_with_validation_error(self) -> None:
        # "I cannot check this" and "I checked this and it is wrong" must not be
        # catchable as one another.
        assert not issubclass(UnsupportedTypeError, ValidationError)
        assert not issubclass(ValidationError, UnsupportedTypeError)
        assert not issubclass(UnsupportedTypeError, TypeError)

    def test_records_the_type(self) -> None:
        error = UnsupportedTypeError(list[int])
        assert error.t == list[int]
        assert error.explanation is None

    def test_records_the_explanation(self) -> None:
        error = UnsupportedTypeError(int, "Because I said so.")
        assert error.explanation == "Because I said so."

    def test_message_names_the_type(self) -> None:
        assert str(UnsupportedTypeError(list[int])) == (
            "Unsupported validation for type list[int]."
        )

    def test_message_appends_the_explanation(self) -> None:
        assert str(UnsupportedTypeError(int, "Because I said so.")) == (
            "Unsupported validation for type <class 'int'>.\nBecause I said so."
        )

    def test_survives_a_pickle_round_trip(self) -> None:
        error = pickle.loads(pickle.dumps(UnsupportedTypeError(int, "Nope.")))
        assert error.t is int
        assert error.explanation == "Nope."

    def test_has_no_instance_dict_entries(self) -> None:
        # BaseException always provides a __dict__, so __slots__ cannot remove
        # it; it can still be kept empty, which is what the slots buy here.
        assert UnsupportedTypeError(int).__dict__ == {}


class TestValidationError:

    def test_is_a_type_error(self) -> None:
        assert issubclass(ValidationError, TypeError)

    def test_records_the_value_and_the_type(self) -> None:
        error = ValidationError("hi", int)
        assert error.val == "hi"
        assert error.t is int

    def test_records_a_falsy_value_faithfully(self) -> None:
        # The value is reported, never tested for truth.
        error = ValidationError(None, int)
        assert error.val is None

    def test_message_names_the_value_and_the_type(self) -> None:
        assert str(ValidationError("hi", int)) == (
            "For type <class 'int'>, invalid value: 'hi'"
        )

    def test_survives_a_pickle_round_trip(self) -> None:
        error = pickle.loads(pickle.dumps(ValidationError("hi", int)))
        assert error.val == "hi"
        assert error.t is int

    def test_has_no_instance_dict_entries(self) -> None:
        assert ValidationError("hi", int).__dict__ == {}

    def test_is_catchable_as_a_type_error(self) -> None:
        # The v1 contract: existing `except TypeError` handlers keep working.
        with pytest.raises(TypeError):
            raise ValidationError("hi", int)


@pytest.mark.parametrize("error", [UnsupportedTypeError, ValidationError])
def test_errors_are_final(error: type[Exception]) -> None:
    # `typing.final` is enforced statically, so this asserts the intent rather
    # than a runtime prohibition: subclassing either error still works at
    # runtime, and mypy is what rejects it.
    assert getattr(error, "__final__", False) is True
