# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The corpus, run through every mechanism.

**Every test here asserts** :class:`~typing_validation.ValidationError`, never
:class:`TypeError`, and never uses a bare ``except``. This is the rule v1 learned
the hard way: its sweep caught the base :class:`TypeError`, so when
``validate(val, typing.NamedTuple)`` crashed inside :func:`isinstance` with a raw
``TypeError: isinstance() arg 2 must be a type…``, the test read the crash as a
correct rejection. The bug and its camouflage shipped together, through eleven
releases. A test that catches the base class cannot tell *"correctly rejected the
value"* from *"the library crashed"*.
"""

from typing import Any

import pytest

from typing_validation import UnsupportedTypeError, ValidationError
from typing_validation.validation import (
    _ITEM_ORIGINS,
    _ITERATOR_ORIGINS,
    _MAPPING_ORIGINS,
    _MAYBE_ITEM_ORIGINS,
)

from .cases import INVALID, UNSUPPORTED, VALID
from .mechanisms import MECHANISM_IDS, MECHANISMS, Mechanism


def _id(case: tuple[Any, Any]) -> str:
    val, t = case
    return f"{t!r}<-{val!r}"[:80]


@pytest.mark.parametrize("mechanism", MECHANISMS, ids=MECHANISM_IDS)
@pytest.mark.parametrize("case", VALID, ids=_id)
def test_valid(mechanism: Mechanism, case: tuple[Any, Any]) -> None:
    val, t = case
    assert mechanism(val, t) is True


@pytest.mark.parametrize("mechanism", MECHANISMS, ids=MECHANISM_IDS)
@pytest.mark.parametrize("case", INVALID, ids=_id)
def test_invalid(mechanism: Mechanism, case: tuple[Any, Any]) -> None:
    val, t = case
    with pytest.raises(ValidationError):
        mechanism(val, t)


@pytest.mark.parametrize("mechanism", MECHANISMS, ids=MECHANISM_IDS)
@pytest.mark.parametrize("case", UNSUPPORTED, ids=_id)
def test_unsupported(mechanism: Mechanism, case: tuple[Any, Any]) -> None:
    val, t = case
    with pytest.raises(UnsupportedTypeError):
        mechanism(val, t)


@pytest.mark.parametrize("mechanism", MECHANISMS, ids=MECHANISM_IDS)
@pytest.mark.parametrize("case", UNSUPPORTED, ids=_id)
def test_unsupported_is_not_a_validation_failure(
    mechanism: Mechanism, case: tuple[Any, Any]
) -> None:
    # "I cannot check this" must never be catchable as "I checked this and it is
    # wrong". A caller branching on the two must be able to.
    val, t = case
    with pytest.raises(UnsupportedTypeError):
        try:
            mechanism(val, t)
        except ValidationError:  # pragma: no cover
            pytest.fail("unsupported type reported as a validation failure")


class TestPurity:
    """
    Validation never mutates or consumes the value it inspects.

    This deserves a real test rather than a convention, because three separate
    parts of the design assume it: union members are tried in sequence and a
    failed attempt must leave nothing behind, the mechanisms must agree on every
    input, and ``diagnose`` re-walks the same value a second time.
    """

    @pytest.mark.parametrize("mechanism", MECHANISMS, ids=MECHANISM_IDS)
    @pytest.mark.parametrize("case", VALID + INVALID, ids=_id)
    def test_the_value_is_unchanged(
        self, mechanism: Mechanism, case: tuple[Any, Any]
    ) -> None:
        val, t = case
        try:
            before = repr(val)
        except Exception:
            pytest.skip("value has no stable repr")
        try:
            mechanism(val, t)
        except ValidationError:
            pass
        assert repr(val) == before

    @pytest.mark.parametrize("mechanism", MECHANISMS, ids=MECHANISM_IDS)
    def test_an_iterator_is_not_consumed(self, mechanism: Mechanism) -> None:
        it = iter([1, 2, 3])
        mechanism(it, Any)
        assert list(it) == [1, 2, 3]


class TestOriginTablesAreDisjoint:
    """
    No origin may appear in two of the dispatch tables.

    This is the structural fix for v1's worst bug rather than a tidiness check.
    ``abc.Iterable`` was in both the iterator table and the maybe-collection
    table; the iterator arm was tested first; the ``Iterable[T]`` item check
    became unreachable dead code and stayed that way for eleven releases. An
    overlap is now a failing test rather than silently dead code.
    """

    TABLES = {
        "item": _ITEM_ORIGINS,
        "mapping": _MAPPING_ORIGINS,
        "iterator": _ITERATOR_ORIGINS,
        "maybe_item": _MAYBE_ITEM_ORIGINS,
    }

    @pytest.mark.parametrize("first", TABLES)
    @pytest.mark.parametrize("second", TABLES)
    def test_pairwise_disjoint(self, first: str, second: str) -> None:
        if first == second:
            return
        overlap = self.TABLES[first] & self.TABLES[second]
        assert not overlap, (
            f"{first} and {second} both claim {overlap}; the earlier arm would "
            f"shadow the later one"
        )
