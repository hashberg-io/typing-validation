# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Tests for the failure tree and the traversal that builds it.

These test the **structure**, not the text. The message format is deliberately
unsettled and owed a round of its own, so asserting on wording now would only
have to be redone — and would pin down by accident the one decision that was
explicitly deferred.
"""

from typing import Any, Iterator, Literal

import pytest

from typing_validation import (
    ValidationError,
    is_valid,
    validate,
    validated_iter,
)
from typing_validation import validation
from typing_validation.diagnosis import (
    Detail,
    DiagnosisFailure,
    Place,
    diagnose,
)

from .cases import INVALID, JSON, Movie, Point, UserId


def _must_not_be_called(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("is_valid must not diagnose")


def _fails(val: Any, t: Any) -> ValidationError:
    with pytest.raises(ValidationError) as info:
        validate(val, t)
    return info.value


class TestTheErrorCarriesTheTree:

    def test_the_failure_hangs_off_the_exception(self) -> None:
        # Reachable as an attribute on the exception you already caught, rather
        # than smuggled on with setattr and fetched by a module-level global.
        error = _fails("a", int)
        assert error.failure is not None
        assert error.failure.t is int
        assert error.failure.val == "a"

    def test_it_is_still_a_type_error(self) -> None:
        with pytest.raises(TypeError):
            validate("a", int)


class TestWhereTheFailureWas:
    """
    The tree must say *where* in the value the failure was, which is what a
    structural description of the type alone cannot do.
    """

    def test_a_plain_mismatch(self) -> None:
        failure = _fails("a", int).failure
        assert failure is not None
        assert failure.detail is Detail.NOT_AN_INSTANCE
        assert failure.causes == ()

    def test_at_a_collection_index(self) -> None:
        failure = _fails([1, "a"], list[int]).failure
        assert failure is not None
        assert failure.detail is Detail.IN_COMPONENT
        (cause,) = failure.causes
        assert cause.location is not None
        assert cause.location.place is Place.INDEX
        assert cause.location.at == 1
        assert cause.val == "a"

    def test_an_unordered_index_is_marked_as_unstable(self) -> None:
        # Iteration order is not stable across runs, so the position is a
        # witness rather than an address, and must not imply otherwise.
        failure = _fails({"a"}, set[int]).failure
        assert failure is not None
        (cause,) = failure.causes
        assert cause.location is not None
        assert cause.location.place is Place.POSITION

    def test_at_a_mapping_key(self) -> None:
        failure = _fails({1: 1}, dict[str, int]).failure
        assert failure is not None
        (cause,) = failure.causes
        assert cause.location is not None
        assert cause.location.place is Place.KEY

    def test_at_a_mapping_value(self) -> None:
        failure = _fails({"a": "b"}, dict[str, int]).failure
        assert failure is not None
        (cause,) = failure.causes
        assert cause.location is not None
        assert cause.location.place is Place.VALUE_AT
        assert cause.location.at == "a"

    def test_nested_two_deep(self) -> None:
        failure = _fails({"a": [1, "b"]}, dict[str, list[int]]).failure
        assert failure is not None
        (outer,) = failure.causes
        (inner,) = outer.causes
        assert inner.val == "b"
        assert inner.location is not None
        assert inner.location.at == 1

    def test_a_union_with_every_member_failing(self) -> None:
        failure = _fails(1.0, list[int] | str).failure
        assert failure is not None
        assert failure.detail is Detail.NO_UNION_MEMBER
        assert len(failure.causes) == 2
        assert all(c.location is not None for c in failure.causes)
        assert {c.location.place for c in failure.causes if c.location} == {
            Place.MEMBER
        }

    def test_a_missing_required_typed_dict_key(self) -> None:
        failure = _fails({"title": "Jaws"}, Movie).failure
        assert failure is not None
        assert failure.detail is Detail.MISSING_KEY

    def test_a_bad_typed_dict_field(self) -> None:
        failure = _fails({"title": "Jaws", "year": "x"}, Movie).failure
        assert failure is not None
        (cause,) = failure.causes
        assert cause.location is not None
        assert cause.location.place is Place.FIELD
        assert cause.location.at == "year"

    def test_a_bad_named_tuple_field(self) -> None:
        failure = _fails(Point("a", 2), Point).failure  # type: ignore[arg-type]
        assert failure is not None
        (cause,) = failure.causes
        assert cause.location is not None
        assert cause.location.place is Place.FIELD
        assert cause.location.at == "x"

    def test_a_wrong_length_tuple(self) -> None:
        failure = _fails((1,), tuple[int, str]).failure
        assert failure is not None
        assert failure.detail is Detail.WRONG_LENGTH

    def test_a_literal_mismatch(self) -> None:
        failure = _fails(3, Literal[1, 2]).failure
        assert failure is not None
        assert failure.detail is Detail.NO_LITERAL

    def test_a_wrapper_reports_itself_and_what_it_wraps(self) -> None:
        # NewType is not stripped: the failure says UserId, and then says the int
        # it turned out not to be.
        failure = _fails("a", UserId).failure
        assert failure is not None
        assert failure.t is UserId
        (cause,) = failure.causes
        assert cause.t is int
        assert cause.location is not None
        assert cause.location.place is Place.WRAPPED


class TestOnlyTheFirstFailingComponent:

    def test_a_conjunctive_failure_reports_one_cause(self) -> None:
        # Every later item would fail too; listing them adds noise, not
        # information.
        failure = _fails(["a", "b", "c"], list[int]).failure
        assert failure is not None
        assert len(failure.causes) == 1
        assert failure.causes[0].location is not None
        assert failure.causes[0].location.at == 0


class TestDiagnosisIsNotRecursive:
    """
    A failure tree is as deep as the *value*.

    ``validate`` handles a list nested twenty thousand deep because it uses a
    work stack; diagnosis needs one for the same reason. Without it, an ordinary
    ``ValidationError`` would come out as a ``RecursionError`` on the way — the
    dishonest error the work stack exists to prevent.
    """

    def test_a_deeply_nested_failure_is_diagnosed(self) -> None:
        val: Any = object()
        for _ in range(20_000):
            val = [val]
        error = _fails(val, JSON)
        assert error.failure is not None

    def test_the_tree_is_as_deep_as_the_value(self) -> None:
        val: Any = object()
        for _ in range(2_000):
            val = [val]
        error = _fails(val, JSON)
        assert error.failure is not None
        assert error.failure.depth() > 2_000

    def test_the_stub_message_does_not_print_the_whole_tree(self) -> None:
        val: Any = object()
        for _ in range(2_000):
            val = [val]
        error = _fails(val, JSON)
        assert len(str(error).splitlines()) < 100

    def test_the_tree_reaches_the_actual_failure(self) -> None:
        val: Any = object()
        for _ in range(5_000):
            val = [val]
        error = _fails(val, JSON)
        assert error.failure is not None
        deepest = list(error.failure.walk())[-1]
        assert deepest.causes == ()


class TestDiagnosisNeverContradictsTheValidator:
    """
    Diagnosis must never answer a reported failure with an implicit *"actually,
    it's fine"*. If it cannot reproduce the failure, a mechanism has drifted from
    the catalogue, and that is a library bug reported as one.
    """

    @pytest.mark.parametrize("case", INVALID, ids=lambda c: repr(c)[:70])
    def test_every_failing_case_is_reproduced(
        self, case: tuple[Any, Any]
    ) -> None:
        # An independent implementation, built on the node model, agreeing with
        # the interpreter on every failing case in the corpus.
        val, t = case
        assert diagnose(val, t) is not None

    def test_a_valid_value_raises_rather_than_reporting_nothing(self) -> None:
        with pytest.raises(DiagnosisFailure):
            diagnose(1, int)

    def test_the_report_asks_for_a_bug_report(self) -> None:
        with pytest.raises(DiagnosisFailure) as info:
            diagnose(1, int)
        assert "report" in str(info.value)


class TestIsValidDoesNotDiagnose:

    def test_no_tree_is_built_for_a_boolean_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A caller who wants the explanation calls validate. v1 built the tree
        # here, so every miss paid for diagnostics nobody had asked for.
        monkeypatch.setattr(validation, "diagnose", _must_not_be_called)
        assert is_valid("a", int) is False


class TestValidatedIter:

    def test_the_offending_item_is_diagnosed(self) -> None:
        it = validated_iter(iter([1, "a"]), Iterator[int])
        with pytest.raises(ValidationError) as info:
            list(it)
        assert info.value.failure is not None
        assert info.value.failure.t is int
