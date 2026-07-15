# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Tests for the extension point.

The hook is the generic-class arm — where the core has run out of things it can
determine on its own, and where v1 gave up next to a ``# TODO`` proposing a
dunder classmethod. The plugin mechanism and that TODO are the same feature.
"""

from collections.abc import Sequence
from typing import Any, Iterator

import pytest

from typing_validation import (
    UnsupportedTypeError,
    ValidationError,
    register_validator,
    validate,
)
from typing_validation.plugins import _PLUGINS, _REGISTRY


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    before = dict(_REGISTRY)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(before)


class Owned[T]:
    """A class we own, which declares how its argument is validated."""

    def __init__(self, item: Any) -> None:
        self.item = item

    @classmethod
    def __validate__(cls, val: Any, args: Sequence[Any]) -> bool:
        from typing_validation import is_valid

        return is_valid(val.item, args[0])


class Foreign[T]:
    """A class we do not own, and so cannot give a dunder to."""

    def __init__(self, item: Any) -> None:
        self.item = item


class Unclaimed[T]:
    """A class with no validator and no plugin: arguments go unchecked."""


class TestDunderProtocol:

    def test_a_declared_class_has_its_arguments_checked(self) -> None:
        assert validate(Owned(1), Owned[int]) is True

    def test_a_declared_class_rejects_a_bad_argument(self) -> None:
        with pytest.raises(ValidationError):
            validate(Owned("a"), Owned[int])

    def test_the_origin_is_still_checked(self) -> None:
        with pytest.raises(ValidationError):
            validate(1, Owned[int])


class TestRegistry:

    def test_a_registered_class_has_its_arguments_checked(self) -> None:
        from typing_validation import is_valid

        register_validator(
            Foreign, lambda val, args: is_valid(val.item, args[0])
        )
        assert validate(Foreign(1), Foreign[int]) is True
        with pytest.raises(ValidationError):
            validate(Foreign("a"), Foreign[int])

    def test_registration_rejects_a_non_class(self) -> None:
        with pytest.raises(TypeError):
            register_validator(42, lambda val, args: True)  # type: ignore[arg-type]

    def test_registration_rejects_a_non_callable(self) -> None:
        with pytest.raises(TypeError):
            register_validator(Foreign, 42)  # type: ignore[arg-type]


class TestUnclaimedGenericClasses:
    """
    A parametrised class nobody has claimed validates on its origin alone.

    This is the specified meaning rather than a shortfall: a generic class does
    not, in general, expose enough at runtime to determine its arguments. It is
    *not* an error to parametrise a class we cannot introspect.
    """

    def test_the_arguments_are_not_checked(self) -> None:
        assert validate(Unclaimed(), Unclaimed[int]) is True

    def test_the_origin_is_checked(self) -> None:
        with pytest.raises(ValidationError):
            validate(1, Unclaimed[int])


class TestClaimedButNotEnabled:
    """
    A class this distribution ships a plugin for, whose plugin is not imported,
    is an **error** rather than an unchecked pass.

    Its arguments *are* determinable, so validating on the origin alone would
    report success we had not earned. This is the one thing that distinguishes
    it from an unclaimed class, and only the plugin table can say so.
    """

    def test_it_raises_rather_than_passing_unchecked(self) -> None:
        _PLUGINS["test"] = "typing_validation.test"
        try:
            with pytest.raises(UnsupportedTypeError) as info:
                validate(Foreign(1), Foreign[int])
            assert "typing_validation.test" in str(info.value)
        finally:
            del _PLUGINS["test"]

    def test_registering_the_validator_settles_it(self) -> None:
        _PLUGINS["test"] = "typing_validation.test"
        try:
            register_validator(Foreign, lambda val, args: True)
            assert validate(Foreign(1), Foreign[int]) is True
        finally:
            del _PLUGINS["test"]


class TestMessages:
    """
    Every unsupported-generic error should teach, which v1's flat *"Unsupported
    validation for type X"* never did.
    """

    def test_the_generic_message_names_both_routes(self) -> None:
        _PLUGINS["test"] = "typing_validation.test"
        try:
            with pytest.raises(UnsupportedTypeError) as info:
                validate(Foreign(1), Foreign[int])
        finally:
            del _PLUGINS["test"]
        message = str(info.value)
        assert "Foreign" in message
        assert "not enabled" in message

    def test_an_unclaimed_class_message_names_both_routes(self) -> None:
        from typing_validation.plugins import unsupported_explanation

        message = unsupported_explanation(Unclaimed)
        assert "__validate__" in message
        assert "register_validator" in message
