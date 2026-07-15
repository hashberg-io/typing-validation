# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Tests for annotation reading and forward-reference resolution.

Most of these encode facts about CPython that are not obvious and that the
implementation leans on directly, so they double as a record of why the code is
shaped the way it is. Where a test asserts something surprising, it says so.
"""

from typing import (
    Annotated,
    List,
    Any,
    Literal,
    NamedTuple,
    NotRequired,
    Optional,
    ReadOnly,
    Required,
    TypedDict,
    Union,
)

import pytest
from annotationlib import ForwardRef

from typing_validation._resolution import (
    field_annotations,
    resolve,
    resolved_field_annotations,
    strip_qualifiers,
)


class Later:
    """A class referred to before it exists, by the fixtures below."""


class TDQualified(TypedDict):
    a: int
    b: NotRequired[str]
    c: ReadOnly[bytes]
    d: NotRequired[ReadOnly[float]]
    e: Required[complex]


class TDForward(TypedDict):
    top: "Later"
    nested: list["Later"]
    deep: dict[str, list["Later"]]
    whole: "list[Later]"
    optional: Optional["Later"]


class TDUnresolvable(TypedDict):
    ok: int
    broken: "NeverDefinedAnywhere"  # type: ignore[name-defined]


class NTForward(NamedTuple):
    top: "Later"
    nested: list["Later"]


class TDBase(TypedDict):
    x: int


class TDDerived(TDBase):
    y: str


class TestStripQualifiers:

    def test_leaves_a_plain_annotation_alone(self) -> None:
        assert strip_qualifiers(int) is int

    @pytest.mark.parametrize(
        "ann", [Required[int], NotRequired[int], ReadOnly[int]]
    )
    def test_strips_each_qualifier(self, ann: Any) -> None:
        assert strip_qualifiers(ann) is int

    def test_strips_nested_qualifiers(self) -> None:
        assert strip_qualifiers(NotRequired[ReadOnly[float]]) is float

    def test_does_not_strip_other_wrappers(self) -> None:
        assert strip_qualifiers(list[int]) == list[int]
        assert strip_qualifiers(Annotated[int, "m"]) == Annotated[int, "m"]


class TestResolve:

    def test_leaves_a_resolved_annotation_untouched(self) -> None:
        assert resolve(list[int], TDForward) == list[int]

    def test_resolves_a_bare_string(self) -> None:
        assert resolve("Later", TDForward) is Later

    def test_resolves_a_forward_ref(self) -> None:
        assert resolve(ForwardRef("Later"), TDForward) is Later

    def test_resolves_a_reference_nested_in_a_generic(self) -> None:
        assert resolve(list["Later"], TDForward) == list[Later]

    def test_resolves_a_reference_nested_two_deep(self) -> None:
        assert (
            resolve(dict[str, list["Later"]], TDForward)
            == dict[str, list[Later]]
        )

    def test_resolves_a_reference_in_a_union(self) -> None:
        assert resolve(Union["Later", int], TDForward) == Union[Later, int]

    def test_resolves_a_reference_under_annotated(self) -> None:
        assert (
            resolve(Annotated["Later", "m"], TDForward) == Annotated[Later, "m"]
        )

    def test_preserves_annotated_metadata(self) -> None:
        resolved = resolve(Annotated[list["Later"], "m"], TDForward)
        assert resolved == Annotated[list[Later], "m"]

    def test_resolves_a_reference_in_a_variadic_tuple(self) -> None:
        assert resolve(tuple["Later", ...], TDForward) == tuple[Later, ...]

    def test_does_not_read_literal_arguments_as_references(self) -> None:
        # Literal's arguments are values. Resolving them would read the 'a' of
        # Literal['a'] as a reference to a class named a.
        assert (
            resolve(Literal["a", "Later"], TDForward) == Literal["a", "Later"]
        )

    def test_leaves_an_unresolvable_reference_in_place(self) -> None:
        resolved = resolve("NeverDefinedAnywhere", TDForward)
        assert isinstance(resolved, ForwardRef)
        assert resolved.__forward_arg__ == "NeverDefinedAnywhere"

    def test_leaves_an_unresolvable_nested_reference_in_place(self) -> None:
        resolved = resolve(
            list["NeverDefinedAnywhere"], TDForward  # type: ignore[name-defined]
        )
        (arg,) = resolved.__args__
        assert isinstance(arg, ForwardRef)

    def test_never_raises_name_error(self) -> None:
        # The whole reason get_type_hints is rejected.
        resolve(
            dict[str, "NeverDefinedAnywhere"],  # type: ignore[name-defined]
            TDForward,
        )

    def test_resolves_a_reference_that_names_a_whole_generic(self) -> None:
        assert resolve("list[Later]", TDForward) == list[Later]


class TestFieldAnnotations:

    def test_reads_annotations_verbatim(self) -> None:
        ann = field_annotations(TDQualified)
        assert ann["a"] is int
        assert ann["b"] == NotRequired[str]

    def test_keeps_qualifiers(self) -> None:
        # annotationlib does not strip them, which is the cost inherited by
        # preferring it over get_type_hints.
        assert field_annotations(TDQualified)["c"] == ReadOnly[bytes]

    def test_includes_inherited_fields(self) -> None:
        assert set(field_annotations(TDDerived)) == {"x", "y"}


class TestResolvedFieldAnnotations:

    def test_strips_qualifiers_and_resolves(self) -> None:
        ann = resolved_field_annotations(TDQualified)
        assert ann == {
            "a": int,
            "b": str,
            "c": bytes,
            "d": float,
            "e": complex,
        }

    def test_resolves_every_reference_shape(self) -> None:
        ann = resolved_field_annotations(TDForward)
        assert ann == {
            "top": Later,
            "nested": list[Later],
            "deep": dict[str, list[Later]],
            "whole": list[Later],
            "optional": Optional[Later],
        }

    def test_resolves_named_tuple_fields(self) -> None:
        # A NamedTuple records no module on its forward references, not even a
        # top-level one, so this only works because the owner is passed.
        assert resolved_field_annotations(NTForward) == {
            "top": Later,
            "nested": list[Later],
        }

    def test_one_unresolvable_field_does_not_poison_the_others(self) -> None:
        # The whole point of resolving field by field.
        ann = resolved_field_annotations(TDUnresolvable)
        assert ann["ok"] is int
        assert isinstance(ann["broken"], ForwardRef)


class TestCPythonFacts:
    """
    Facts about CPython 3.14 that the module above is built on. Each was
    verified rather than assumed, and each would silently change the meaning of
    the code if it stopped holding.
    """

    def test_annotations_stay_frozen_as_forward_refs(self) -> None:
        # `Later` exists by now, yet the annotation is still a ForwardRef:
        # TypedDict and NamedTuple snapshot their annotations at class creation.
        # So something must resolve them; that something is this module.
        assert isinstance(TDForward.__annotations__["top"], ForwardRef)

    def test_only_a_top_level_typed_dict_reference_records_a_module(
        self,
    ) -> None:
        top = TDForward.__annotations__["top"]
        assert top.__forward_module__ is not None
        nested = TDForward.__annotations__["nested"].__args__[0]
        assert isinstance(nested, str)
        assert NTForward.__annotations__["top"].__forward_module__ is None

    def test_generic_aliases_still_have_copy_with(self) -> None:
        # The library's only dependency on a private API. It is used to rebuild a
        # typing.List["X"] as a typing.List[X] rather than a list[X], because the
        # two are unequal and hash differently, and rewriting the spelling only
        # when a reference happened to need resolving would be worse than not
        # supporting it. If this ever disappears, fail here rather than silently
        # dropping the deprecated spellings.
        assert hasattr(List[int], "copy_with")
        assert List[int] != list[int]

    def test_a_nested_reference_degrades_to_a_bare_string(self) -> None:
        # list["Later"] stores the str 'Later', not a ForwardRef at all.
        (arg,) = TDForward.__annotations__["nested"].__args__
        assert arg == "Later"
        assert isinstance(arg, str)
