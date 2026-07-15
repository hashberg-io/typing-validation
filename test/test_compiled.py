# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Tests for ``compiled_validator``, beyond the corpus.

The corpus reaches it through the mechanism axis. These cover what the corpus
cannot see: the *shape* of the emitted code, which is the entire claim. That a
loop was unrolled, that a cycle became a call, that a plugin became a call, and
that the budget was obeyed are all invisible to a test that only runs the result
and sees ``True``.
"""

import sys
from typing import Any, Callable, NamedTuple, TypedDict

import numpy as np
import pytest
import typing_validation.numpy  # noqa: F401
from numpy.typing import NDArray

from typing_validation import (
    UnsupportedTypeError,
    ValidationError,
    compiled_validator,
    validate,
    validator,
)
from typing_validation.emission import _INLINE_BUDGET, source_for

type JSON = int | str | bool | None | list[JSON] | dict[str, JSON]


class Point(NamedTuple):
    x: int
    y: int


class Movie(TypedDict):
    title: str
    year: int


class TestContract:

    def test_returns_true(self) -> None:
        assert compiled_validator(list[int])([1, 2]) is True

    def test_raises_a_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            compiled_validator(list[int])([1, "a"])

    def test_the_error_explains_itself(self) -> None:
        with pytest.raises(ValidationError) as info:
            compiled_validator(dict[str, list[int]])({"a": [1, "b"]})
        assert "value['a'][1]" in str(info.value)

    def test_unsupported_is_refused_at_construction(self) -> None:
        with pytest.raises(UnsupportedTypeError):
            compiled_validator(list[Callable[[int], int]])


class TestTheEmittedShape:
    """
    The claim is about the *code*, so these read it.

    A test that only runs the result cannot tell code that was unrolled from code
    that quietly called into the composed validator — both answer ``True`` — and
    the difference is the entire reason this mechanism exists.
    """

    def test_a_collection_becomes_a_loop(self) -> None:
        src = source_for(list[int])
        assert "for _i0 in _v:" in src
        assert "isinstance" in src
        # Unrolled, so nothing was handed off.
        assert "_call" not in src

    def test_a_mapping_becomes_a_loop_over_items(self) -> None:
        src = source_for(dict[str, int])
        assert ".items():" in src
        assert "_call" not in src

    def test_a_fixed_tuple_is_unrolled_by_index(self) -> None:
        src = source_for(tuple[int, str])
        assert "_v[0]" in src and "_v[1]" in src
        assert "len(_v) != 2" in src
        assert "for " not in src

    def test_nesting_is_unrolled_all_the_way_down(self) -> None:
        src = source_for(list[dict[str, int]])
        assert "for _i0 in _v:" in src
        assert ".items():" in src
        assert "_call" not in src

    def test_a_union_of_plain_classes_is_one_isinstance(self) -> None:
        src = source_for(int | None)
        assert src.count("isinstance") == 1

    def test_a_typed_dict_checks_required_keys_by_name(self) -> None:
        src = source_for(Movie)
        assert "'title' not in _v" in src
        assert "'year' not in _v" in src

    def test_a_named_tuple_reaches_fields_by_attribute(self) -> None:
        src = source_for(Point)
        assert "_v.x" in src and "_v.y" in src

    def test_any_emits_no_check_at_all(self) -> None:
        # Every value is valid, so there is nothing to say.
        src = source_for(Any)
        assert "isinstance" not in src
        assert "return False" not in src


class TestWhereUnrollingStops:

    def test_a_cycle_becomes_a_call(self) -> None:
        # Unrolling a recursive alias does not terminate, and the value it
        # accepts has no depth bound, so this is where the loop has to be a
        # runtime one.
        assert "_call" in source_for(JSON)

    def test_a_type_over_budget_becomes_a_call(self) -> None:
        wide: Any = int
        for _ in range(_INLINE_BUDGET + 10):
            wide = list[wide]
        assert "_call" in source_for(wide)

    def test_a_type_under_budget_does_not(self) -> None:
        small: Any = int
        for _ in range(3):
            small = list[small]
        assert "_call" not in source_for(small)

    def test_a_plugin_becomes_a_call(self) -> None:
        # The compiler has no source for a plugin's check and can only call into
        # it. Unavoidable, and worth stating rather than discovering.
        assert "_call" in source_for(NDArray[np.uint8])


class TestDepth:
    """
    Why unrolling is safe at all.

    Unrolled loops nest once per level of the *type*, and an acyclic type bounds
    the value: list[int] against a value nested twenty thousand deep fails its
    isinstance at level two and never descends. A cycle removes the bound, and is
    exactly where the emitted code stops unrolling.
    """

    DEPTH = 20_000

    def _nest(self, innermost: Any) -> Any:
        val = innermost
        for _ in range(self.DEPTH):
            val = [val]
        return val

    def test_an_acyclic_type_cannot_recurse_however_deep_the_value(
        self,
    ) -> None:
        assert self.DEPTH > sys.getrecursionlimit()
        with pytest.raises(ValidationError):
            compiled_validator(list[int])(self._nest(1))

    def test_a_deep_value_through_a_recursive_alias(self) -> None:
        assert compiled_validator(JSON)(self._nest("x")) is True

    def test_a_deep_value_is_still_rejected(self) -> None:
        with pytest.raises(ValidationError):
            compiled_validator(JSON)(self._nest(object()))


class TestAgreement:

    @pytest.mark.parametrize(
        "case",
        [
            ({"a": [1, "b", None]}, JSON),
            ({"a": [1.5]}, JSON),
            ({"a": [1, {"b": 1.5}]}, JSON),
            ([1, 2, 3], list[int]),
            ([1, "a"], list[int]),
            (Point(1, 2), Point),
            (Point("a", 2), Point),  # type: ignore[arg-type]
            ({"title": "J", "year": 1}, Movie),
            ({"title": "J"}, Movie),
        ],
        ids=lambda c: repr(c)[:40],
    )
    def test_all_three_mechanisms_agree(self, case: tuple[Any, Any]) -> None:
        # The bad item behind a push is what caught a real bug here: the emitted
        # code called the composed check with a throwaway stack, so the work was
        # silently dropped and an invalid value came back valid.
        val, t = case
        runs: list[Callable[[], bool]] = [
            lambda: validate(val, t),
            lambda: validator(t)(val),
            lambda: compiled_validator(t)(val),
        ]
        results: list[bool] = []
        for run in runs:
            try:
                results.append(run())
            except ValidationError:
                results.append(False)
        assert len(set(results)) == 1, f"mechanisms disagree: {results}"
