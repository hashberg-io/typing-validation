# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Tests for the node model, interning, and the questions asked of a type.
"""

from typing import Annotated, Any, Callable, Iterator, Literal, Self, Union

import pytest

from typing_validation import (
    TypeForm,
    UnsupportedTypeError,
    can_validate,
    clear_cache,
    forget_type,
    inspect_type,
    scoped_cache,
    validate,
)
from typing_validation.cache import _TIERS
from typing_validation.nodes import node_for

from .cases import (
    INVALID,
    UNSUPPORTED_TYPES,
    VALID,
    JSON,
    Aliased,
    Box,
    Movie,
    MyInt,
    Point,
    UserId,
)

type PoisonedCycle = list[PoisonedCycle] | Callable[[int], int]
"""A recursive type whose cycle is not the problem: the ``Callable`` is."""


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    clear_cache()
    yield
    clear_cache()


class TestForms:

    @pytest.mark.parametrize(
        "t, form",
        [
            (Any, TypeForm.ANY),
            (None, TypeForm.NONE),
            (type(None), TypeForm.NONE),
            (int, TypeForm.CLASS),
            (list, TypeForm.CLASS),
            (list[int], TypeForm.COLLECTION),
            (dict[str, int], TypeForm.MAPPING),
            (tuple[int, str], TypeForm.TUPLE),
            (tuple[int, ...], TypeForm.TUPLE),
            (int | str, TypeForm.UNION),
            (Literal[1], TypeForm.LITERAL),
            (Movie, TypeForm.TYPED_DICT),
            (Point, TypeForm.NAMED_TUPLE),
            (type[int], TypeForm.TYPE_OF),
            (Box[int], TypeForm.GENERIC_CLASS),
            (MyInt, TypeForm.ALIAS),
            (Annotated[int, "m"], TypeForm.ANNOTATED),
            (UserId, TypeForm.NEW_TYPE),
            (Iterator[int], TypeForm.ITERATOR),
            (Callable[[int], int], TypeForm.UNSUPPORTED),
        ],
    )
    def test_form(self, t: Any, form: TypeForm) -> None:
        assert inspect_type(t).form is form

    def test_children_are_the_component_types(self) -> None:
        node = inspect_type(dict[str, list[int]])
        assert [child.t for child in node.children] == [str, list[int]]

    def test_typed_dict_children_are_labelled_by_field(self) -> None:
        node = inspect_type(Movie)
        assert node.labels == ("title", "year")
        assert [child.t for child in node.children] == [str, int]

    def test_named_tuple_children_are_labelled_by_field(self) -> None:
        node = inspect_type(Point)
        assert node.labels == ("x", "y")

    def test_a_literal_has_no_children(self) -> None:
        # Its arguments are values, not types.
        assert inspect_type(Literal[1, "a"]).children == ()

    def test_a_generic_class_has_no_children(self) -> None:
        # Its arguments do not bear on the verdict, so they are not components.
        assert inspect_type(Box[int]).children == ()

    def test_an_alias_is_not_transparent(self) -> None:
        node = inspect_type(MyInt)
        assert node.form is TypeForm.ALIAS
        assert node.t is MyInt
        assert node.children[0].t is int

    def test_annotated_keeps_its_metadata_in_the_type(self) -> None:
        node = inspect_type(Annotated[int, "m"])
        assert node.t == Annotated[int, "m"]
        assert node.children[0].t is int


class TestTotality:

    @pytest.mark.parametrize("t", UNSUPPORTED_TYPES, ids=lambda t: repr(t)[:60])
    def test_unsupported_types_cannot_be_validated(self, t: Any) -> None:
        assert can_validate(t) is False

    @pytest.mark.parametrize(
        "t",
        [int, list[int], dict[str, int], Movie, Point, JSON, Aliased, Box[int]],
        ids=repr,
    )
    def test_supported_types_can_be_validated(self, t: Any) -> None:
        assert can_validate(t) is True

    def test_one_unsupported_component_poisons_the_whole_type(self) -> None:
        assert can_validate(tuple[int, Callable[[int], int]]) is False
        assert can_validate(list[list[Callable[[int], int]]]) is False
        assert can_validate(dict[str, Self]) is False

    def test_poisoning_is_reported_precisely(self) -> None:
        node = inspect_type(tuple[int, Callable[[int], int]])
        (culprit,) = node.unsupported_components()
        assert culprit.t == Callable[[int], int]
        assert culprit.reason is not None

    def test_the_whole_structure_is_still_reported(self) -> None:
        # Unsupported must never be opaque.
        node = inspect_type(tuple[int, Callable[[int], int]])
        assert [child.t for child in node.children] == [
            int,
            Callable[[int], int],
        ]

    def test_a_cycle_alone_does_not_make_a_type_unsupported(self) -> None:
        assert can_validate(JSON) is True

    def test_a_cycle_does_not_hide_an_unsupported_component(self) -> None:
        # The trap that makes a single settling pass wrong: list[Bad] reads Bad
        # as supported while Bad is still being built, and only afterwards does
        # Bad turn out to be poisoned by the Callable.
        assert can_validate(PoisonedCycle) is False
        assert can_validate(list[PoisonedCycle]) is False


class TestAgreementWithTheInterpreter:
    """
    ``can_validate`` and the interpreter must not disagree about support.

    The interpreter is lazier — it raises only when it *reaches* an unsupported
    component — so the property is one-directional: whatever ``can_validate``
    accepts, the interpreter must never call unsupported.
    """

    @pytest.mark.parametrize(
        "case", VALID + INVALID, ids=lambda c: repr(c)[:70]
    )
    def test_the_interpreter_honours_everything_can_validate_accepts(
        self, case: tuple[Any, Any]
    ) -> None:
        val, t = case
        assert can_validate(t) is True
        try:
            validate(val, t)
        except UnsupportedTypeError:  # pragma: no cover
            pytest.fail("can_validate accepted a type the interpreter refused")
        except Exception:
            pass


class TestRecursion:

    def test_a_recursive_alias_terminates(self) -> None:
        node = inspect_type(JSON)
        assert node.form is TypeForm.ALIAS

    def test_the_cycle_closes_on_the_same_node(self) -> None:
        # Hash-consing before descending is what makes this true, and what makes
        # construction terminate at all.
        node = inspect_type(JSON)
        reachable = {id(n) for n in node.walk()}
        alias_nodes = [n for n in node.walk() if n.t is JSON]
        assert len(alias_nodes) == 1
        assert id(alias_nodes[0]) in reachable

    def test_walking_a_recursive_type_terminates(self) -> None:
        assert len(list(inspect_type(JSON).walk())) > 1


class TestInterning:

    def test_the_same_type_yields_the_same_node(self) -> None:
        assert inspect_type(list[int]) is inspect_type(list[int])

    def test_structurally_equal_types_share(self) -> None:
        assert node_for(dict[str, list[int]]).children[1] is node_for(list[int])

    def test_distinctions_python_keeps_are_kept(self) -> None:
        assert inspect_type(MyInt) is not inspect_type(int)
        assert inspect_type(UserId) is not inspect_type(int)
        assert inspect_type(Annotated[int, "a"]) is not inspect_type(
            Annotated[int, "b"]
        )

    def test_unions_merge_because_python_merges_them(self) -> None:
        # The one price of keying on t itself, paid knowingly: Python considers
        # these equal and hashes them equally, so any cache keyed on t merges
        # them. They are the same type.
        assert inspect_type(Union[int, str]) is inspect_type(Union[str, int])


class TestInterningIsNeverObservable:
    """
    A cold, cleared or bypassed cache must not change any verdict.

    This is a hard invariant rather than an aspiration, and it is what licenses
    the eviction API to exist at all.
    """

    @pytest.mark.parametrize("case", VALID, ids=lambda c: repr(c)[:70])
    def test_a_cold_cache_agrees_with_a_warm_one(
        self, case: tuple[Any, Any]
    ) -> None:
        _, t = case
        cold = can_validate(t)
        warm = can_validate(t)
        clear_cache()
        again = can_validate(t)
        assert cold is warm is again

    def test_an_unhashable_type_is_supported_but_unshared(self) -> None:
        # Annotated[int, {"ge": 0}] is unhashable, because metadata participates
        # in the hash — and that is exactly the idiom the Annotated decision
        # exists to accommodate, so it is not a corner case.
        t = Annotated[int, {"ge": 0}]
        with pytest.raises(TypeError):
            hash(t)
        assert can_validate(t) is True
        assert validate(1, t) is True
        assert inspect_type(t) is not inspect_type(t)

    def test_an_unhashable_type_nested_inside_a_hashable_one(self) -> None:
        t = list[Annotated[int, {"ge": 0}]]
        assert can_validate(t) is True
        assert validate([1], t) is True


class TestCacheManagement:

    def test_clearing_empties_the_cache(self) -> None:
        inspect_type(list[int])
        clear_cache()
        assert not any(_TIERS)

    def test_forgetting_drops_one_type(self) -> None:
        node = inspect_type(list[int])
        assert forget_type(list[int]) is True
        assert inspect_type(list[int]) is not node

    def test_forgetting_an_absent_type_reports_so(self) -> None:
        assert forget_type(list[float]) is False

    def test_forgetting_an_unhashable_type_is_not_an_error(self) -> None:
        assert forget_type(Annotated[int, {"ge": 0}]) is False


class TestScopedCache:

    def test_nodes_created_inside_are_dropped_on_exit(self) -> None:
        with scoped_cache():
            inner = inspect_type(list[float])
        assert inspect_type(list[float]) is not inner

    def test_nodes_created_outside_survive(self) -> None:
        outer = inspect_type(list[int])
        with scoped_cache():
            assert inspect_type(list[int]) is outer
        assert inspect_type(list[int]) is outer

    def test_an_inner_node_may_reference_an_outer_one(self) -> None:
        # References only ever point outward, which is what makes dropping a
        # tier whole safe: the outer node outlives the inner one.
        outer = inspect_type(list[int])
        with scoped_cache():
            inner = inspect_type(dict[str, list[int]])
            assert inner.children[1] is outer

    def test_dropping_a_tier_changes_no_answer(self) -> None:
        with scoped_cache():
            inside = can_validate(JSON)
        assert can_validate(JSON) is inside

    def test_tiers_nest(self) -> None:
        with scoped_cache():
            middle = inspect_type(list[complex])
            with scoped_cache():
                assert inspect_type(list[complex]) is middle
                innermost = inspect_type(list[bytes])
            assert inspect_type(list[bytes]) is not innermost
            assert inspect_type(list[complex]) is middle
