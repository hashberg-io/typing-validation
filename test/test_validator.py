# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Tests for ``validator``, beyond the corpus.

The corpus already runs through it — that is what the mechanism axis is for, and
adding it there was one line. These cover what the corpus cannot see: that the
closures are shared rather than rebuilt, that a cycle closes, that deep values do
not overflow anything, and that construction refuses an unsupported type up front
where the interpreter would wait.
"""

import sys
from typing import Any, Callable, Iterator, Literal, NamedTuple, TypedDict

import pytest

from typing_validation import (
    UnsupportedTypeError,
    ValidationError,
    clear_cache,
    validate,
    validator,
)
from typing_validation.nodes import node_for

type JSON = int | str | bool | None | list[JSON] | dict[str, JSON]
type Rec = int | list[Rec]


class Point(NamedTuple):
    x: int
    y: int


class Movie(TypedDict):
    title: str
    year: int


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    clear_cache()
    yield
    clear_cache()


class TestContract:

    def test_returns_true(self) -> None:
        assert validator(list[int])([1, 2]) is True

    def test_raises_a_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            validator(list[int])([1, "a"])

    def test_the_error_explains_itself(self) -> None:
        # The same explanation validate gives, because there is only one place
        # explanations are built.
        with pytest.raises(ValidationError) as info:
            validator(dict[str, list[int]])({"a": [1, "b"]})
        assert info.value.failure is not None
        assert "value['a'][1]" in str(info.value)

    def test_one_validator_serves_many_values(self) -> None:
        check = validator(list[int])
        assert all(check([i]) for i in range(100))


class TestUnsupportedIsRefusedAtConstruction:
    """
    ``validator`` cannot be lazy the way the interpreter is: it analyses the whole
    type before it sees a value, so an unsupported component is fatal up front.

    This is the one place the two mechanisms are *meant* to differ, and the
    conformance property is written to allow exactly it.
    """

    def test_construction_raises(self) -> None:
        with pytest.raises(UnsupportedTypeError):
            validator(list[Callable[[int], int]])

    def test_the_interpreter_is_lazier_about_the_same_type(self) -> None:
        # No value reaches the Callable, so the interpreter never notices.
        assert validate([], list[Callable[[int], int]]) is True

    def test_the_error_names_the_culprit(self) -> None:
        with pytest.raises(UnsupportedTypeError) as info:
            validator(tuple[int, Callable[[int], int]])
        assert info.value.explanation is not None
        assert "signature" in info.value.explanation


class TestSharing:
    """
    Nodes are interned, so a sub-type is analysed once and its closure reused
    everywhere it occurs — the graph is over distinct sub-types, not over
    syntactic occurrences.
    """

    def test_a_shared_subtype_is_composed_once(self) -> None:
        validator(dict[str, list[int]])
        inner = node_for(list[int])
        assert inner._check is not None
        composed = inner._check
        validator(tuple[list[int], ...])
        # The same closure object, reached through a different type.
        assert node_for(list[int])._check is composed

    def test_building_twice_reuses_the_composition(self) -> None:
        validator(list[int])
        first = node_for(list[int])._check
        validator(list[int])
        assert node_for(list[int])._check is first

    def test_a_cleared_cache_changes_no_answer(self) -> None:
        before = validator(JSON)({"a": [1, "b", None]})
        clear_cache()
        assert validator(JSON)({"a": [1, "b", None]}) is before


class TestRecursion:

    def test_a_recursive_alias_closes(self) -> None:
        check = validator(JSON)
        assert check({"a": [1, "b", {"c": None}]}) is True

    def test_a_recursive_alias_still_rejects(self) -> None:
        with pytest.raises(ValidationError):
            validator(JSON)({"a": [1.5]})

    def test_the_back_edge_is_late_bound(self) -> None:
        # The cycle cannot be closed by capturing a closure that does not exist
        # yet, so the back-edge reads the node's slot at call time. If that were
        # captured instead, building would either recurse for ever or capture
        # None and fail on the first cyclic value.
        assert validator(Rec)([[[1]]]) is True


class TestDepth:
    """
    What the composition shape exists for.

    Closures that call one another are faster and raise ``RecursionError`` here;
    closures that all push are safe and barely beat the interpreter. Calling the
    children that cannot descend and pushing the ones that can is both.
    """

    DEPTH = 20_000

    def _nest(self, innermost: Any) -> Any:
        val = innermost
        for _ in range(self.DEPTH):
            val = [val]
        return val

    def test_a_deep_value_through_a_recursive_alias(self) -> None:
        assert self.DEPTH > sys.getrecursionlimit()
        assert validator(JSON)(self._nest("x")) is True

    def test_a_deep_value_is_still_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validator(Rec)(self._nest("x"))

    def test_a_deep_type(self) -> None:
        t: Any = int
        val: Any = 1
        for _ in range(5_000):
            t = list[t]
            val = [val]
        assert validator(t)(val) is True

    def test_the_interpreter_agrees_on_all_of_it(self) -> None:
        val = self._nest("x")
        assert validate(val, JSON) is validator(JSON)(val)


class TestCallVersusPush:
    """
    The distinction that makes the shape work, checked where it is decidable.

    A check that cannot descend is called by its parent; one that can is pushed.
    Getting this wrong is not a crash but a silent loss of speed or safety, so it
    is worth pinning rather than trusting.
    """

    @pytest.mark.parametrize(
        "t",
        [
            int,
            str,
            None,
            Literal[1, 2],
            int | None,
            int | str | None,
            type[int],
        ],
        ids=repr,
    )
    def test_these_cannot_descend(self, t: Any) -> None:
        validator(t)
        assert node_for(t)._can_push is False

    @pytest.mark.parametrize(
        "t",
        [list[int], dict[str, int], tuple[int, str], Movie, Point, JSON],
        ids=repr,
    )
    def test_these_can(self, t: Any) -> None:
        validator(t)
        assert node_for(t)._can_push is True

    def test_a_union_of_plain_classes_collapses(self) -> None:
        # It has children and still cannot descend: it is one isinstance against
        # the argument tuple. A parent may call it.
        validator(int | str | None)
        assert node_for(int | str | None)._can_push is False

    def test_a_union_with_a_structured_member_does_not(self) -> None:
        validator(list[int] | str)
        assert node_for(list[int] | str)._can_push is True

    def test_a_wrapper_inherits_from_what_it_wraps(self) -> None:
        type ShallowAlias = int
        type DeepAlias = list[int]
        validator(ShallowAlias)
        validator(DeepAlias)
        assert node_for(ShallowAlias)._can_push is False
        assert node_for(DeepAlias)._can_push is True
