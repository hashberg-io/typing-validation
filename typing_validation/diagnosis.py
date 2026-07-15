# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Explaining a failure, after the fact.

The validators fail hard and say only *that* they failed. Everything a user reads
about *why* is produced here, by a slower second traversal of the same
``(val, t)``. This is the single most valuable consequence of the architecture:
because diagnostics are produced in exactly one place, there is exactly one
implementation of them — so the conformance obligation between mechanisms reduces
to *"do they agree on the boolean"*, which is a far smaller thing to police than
*"do they agree on the message"*.

And because this runs only on a failure, which is by definition exceptional, it
may be as slow, allocating and thorough as it likes. It is, in effect, v1's
``validate`` — rich and allocating — demoted from the hot path to diagnostics
duty, where its costs stop mattering and its quality is the entire point.

The second traversal is sound only because validation is pure: the value handed
here is the value the validator saw, undisturbed.
"""

import enum
import typing
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Union, final

from .nodes import TypeForm, TypeNode, node_for

__all__ = (
    "Detail",
    "Place",
    "Location",
    "ValidationFailure",
    "diagnose",
)


@final
class Detail(enum.Enum):
    """Why one node of a failure tree failed."""

    NOT_AN_INSTANCE = "not an instance"
    """The value is not an instance of the type, or of the type's origin."""

    NOT_NONE = "not None"
    """The type is ``None`` and the value is not."""

    NO_LITERAL = "no matching literal"
    """The value equals none of the literals, at its own type."""

    WRONG_LENGTH = "wrong length"
    """A fixed-length tuple of the wrong size."""

    MISSING_KEY = "missing required key"
    """A ``TypedDict`` required key that is absent."""

    NON_STRING_KEY = "key is not a string"
    """A ``TypedDict`` key that is not a string."""

    NOT_A_CLASS = "not a class"
    """``Type[T]`` was given something that is not a class."""

    NOT_A_SUBCLASS = "not a subclass"
    """``Type[T]`` was given a class that does not derive from ``T``."""

    NOT_A_NAMED_TUPLE = "not a named tuple"
    """Bare ``typing.NamedTuple`` was given something that is not one."""

    NO_UNION_MEMBER = "no member matched"
    """Every member of a union failed. The causes say how each one did."""

    PLUGIN_REJECTED = "rejected by plugin"
    """A plugin's own check said no, and offered no further detail."""

    IN_COMPONENT = "a component failed"
    """
    This node is fine in itself; something inside it is not. The causes say what,
    and their locations say where.
    """


@final
class Place(enum.Enum):
    """What kind of position a failure occupies within its parent value."""

    INDEX = "index"
    """A position in an ordered collection, which is addressable."""

    POSITION = "position"
    """
    A position in an *unordered* collection.

    Iteration order is **not stable across runs**, so this is a witness that
    something failed, not an address the user can go to. It must be reported as
    such rather than implying a location.
    """

    KEY = "key"
    """A mapping key that is itself invalid."""

    VALUE_AT = "value at key"
    """The value stored under a mapping key."""

    FIELD = "field"
    """A named field of a ``TypedDict`` or named tuple."""

    MEMBER = "union member"
    """One alternative of a union, all of which failed."""

    WRAPPED = "wrapped type"
    """
    What an alias, ``Annotated``, ``NewType`` or type variable resolves to.

    The wrapper is not transparent: it reports as itself and the cause reports
    what it stands for.
    """


@final
@dataclass(frozen=True, slots=True)
class Location:
    """Where a failure sits inside the value that contains it."""

    place: Place
    """What kind of position this is."""

    at: Any = None
    """The index, key or field name, where the place has one."""


@final
@dataclass(frozen=True, slots=True, eq=False, repr=False)
class ValidationFailure:
    """
    One node of a failure tree: a value, the type it failed against, why, and
    what failed inside it.

    Nothing here recurses over ``causes``, and that is not fastidiousness. A
    failure tree is as deep as the *value*, so the generated ``__repr__`` and
    ``__eq__`` would raise :class:`RecursionError` on exactly the deeply nested
    values the rest of this library goes out of its way to handle — turning an
    ordinary failure into a stack overflow at the moment someone tries to look at
    it. So they are turned off and replaced with iterative equivalents.
    """

    val: Any
    """The value that failed."""

    t: Any
    """The type it failed against."""

    detail: Detail
    """Why it failed."""

    location: Location | None = None
    """Where this sits within the value that contains it. :obj:`None` at the root."""

    causes: tuple[ValidationFailure, ...] = ()
    """The failures inside this one."""

    def walk(self) -> Iterator[ValidationFailure]:
        """Every failure in the tree, this one first, depth-first."""
        stack = [self]
        while stack:
            failure = stack.pop()
            yield failure
            stack.extend(reversed(failure.causes))

    def depth(self) -> int:
        """How deep the tree goes."""
        deepest = 0
        stack = [(self, 1)]
        while stack:
            failure, level = stack.pop()
            deepest = max(deepest, level)
            stack.extend((cause, level + 1) for cause in failure.causes)
        return deepest

    def __repr__(self) -> str:
        return (
            f"<ValidationFailure {self.t!r}: {self.detail.value}, "
            f"{len(self.causes)} cause(s)>"
        )

    def __str__(self) -> str:
        # STUB. The message format is deliberately unsettled and owed a round of
        # its own, deferred until the rest of 2.0 is in place: it lives in
        # exactly one place, so it is cheap to settle once and expensive to
        # relitigate. This renders the tree faithfully enough to read while that
        # decision is outstanding, and is not the format.
        lines: list[str] = []
        stack: list[tuple[ValidationFailure, int]] = [(self, 0)]
        while stack:
            failure, depth = stack.pop()
            if depth > _STUB_MESSAGE_DEPTH:
                lines.append("  " * depth + "...")
                continue
            lines.append(failure._line(depth))
            stack.extend(
                (cause, depth + 1) for cause in reversed(failure.causes)
            )
        return "\n".join(lines)

    def _line(self, depth: int) -> str:
        pad = "  " * depth
        where = ""
        if self.location is not None:
            where = f" {self.location.place.value}"
            if self.location.at is not None:
                where += f" {self.location.at!r}"
        line = f"{pad}For type {self.t!r}{where}: {self.detail.value}"
        if not self.causes:
            line += f", got {self.val!r}"
        return line


_STUB_MESSAGE_DEPTH = 20
"""
How deep the stub renderer goes before eliding.

A failure twenty thousand levels down is a real failure and the tree records it
in full; printing all of it would help nobody. Where the cut belongs, and whether
it belongs at all, is part of the deferred message-format decision.
"""


@final
class DiagnosisFailure(RuntimeError):
    """
    Raised when a validator reports a failure that diagnosis cannot reproduce.

    This is a **library bug** — a mechanism has drifted from the catalogue — and
    it is reported as one. Diagnosis must never answer a reported failure with an
    implicit *"actually, it's fine"*: the failure is not swallowed, and no
    validation error is quietly downgraded to success.
    """


def diagnose(val: Any, t: Any, /) -> ValidationFailure:
    """
    Explain why a value is not valid for a type.

    :param val: the value that failed.
    :param t: the type it failed against.
    :raises DiagnosisFailure: if the value turns out to be valid after all, which
        means a mechanism has drifted from the specification.
    """
    failure = _diagnose(val, t)
    if failure is None:
        raise DiagnosisFailure(
            f"Validation of {val!r} against {t!r} failed, but diagnosis could "
            f"not reproduce the failure. This is a bug in typing-validation; "
            f"please report it."
        )
    return failure


@dataclass(slots=True)
class _Frame:
    """
    One node of the traversal, part-built.

    Mutable, unlike everything it produces: a tree is built from the bottom up
    and a frame accumulates its causes as its children report back.
    """

    val: Any
    t: Any
    location: Location | None
    detail: Detail
    todo: list[tuple[Any, Any, Location]] = field(default_factory=list)
    causes: list[ValidationFailure] = field(default_factory=list)
    any_member_passed: bool = False
    is_union: bool = False
    settled: bool = False
    """Set once the outcome is known and no further children need examining."""


def _diagnose(val: Any, t: Any, /) -> ValidationFailure | None:
    """
    The traversal proper, iterative for the same reason the interpreter is.

    The design called this recursive, on the grounds that it runs only on
    failures and may be as slow as it likes. Slow it may be; deep it may not.
    A failure tree is as deep as the *value*, so a list nested twenty thousand
    deep — which ``validate`` handles precisely because it uses a work stack —
    would fail here with ``RecursionError`` on the way out of a perfectly
    ordinary ``ValidationError``. Turning a validation failure into a stack
    overflow is exactly the dishonest error the work stack exists to prevent, so
    diagnosis gets one too.
    """
    stack = [_expand(val, t, None)]
    result: ValidationFailure | None = None
    have_result = False
    while stack:
        frame = stack[-1]
        if have_result:
            have_result = False
            if frame.is_union:
                if result is None:
                    # A member passed, so the union is satisfied and whatever
                    # the validator saw is not here.
                    frame.any_member_passed = True
                    frame.settled = True
                else:
                    frame.causes.append(result)
            elif result is not None:
                # Everything else is conjunctive: the first failing component is
                # the one to report, and looking further would only add noise.
                frame.causes.append(result)
                frame.settled = True
        if not frame.settled and frame.todo:
            child_val, child_t, location = frame.todo.pop(0)
            stack.append(_expand(child_val, child_t, location))
            continue
        stack.pop()
        result = _finish(frame)
        have_result = True
    return result


def _finish(frame: _Frame, /) -> ValidationFailure | None:
    if frame.is_union:
        if frame.any_member_passed:
            return None
        return ValidationFailure(
            frame.val,
            frame.t,
            Detail.NO_UNION_MEMBER,
            frame.location,
            tuple(frame.causes),
        )
    if frame.detail is Detail.IN_COMPONENT and not frame.causes:
        return None
    return ValidationFailure(
        frame.val, frame.t, frame.detail, frame.location, tuple(frame.causes)
    )


def _ok(val: Any, t: Any, location: Location | None, /) -> _Frame:
    """A frame that fails only if one of its children does."""
    return _Frame(val, t, location, Detail.IN_COMPONENT)


def _bad(
    val: Any, t: Any, location: Location | None, detail: Detail, /
) -> _Frame:
    """A frame that has already failed, with no children to examine."""
    frame = _Frame(val, t, location, detail)
    frame.settled = True
    return frame


def _expand(val: Any, t: Any, location: Location | None, /) -> _Frame:
    """
    Work out whether a value fails against a type, and what to look at next.

    This reads the node model rather than re-deriving the type's shape, which
    costs nothing here: nodes are interned, this runs only on failures, and
    ``inspect_type`` had to build the graph anyway. The interpreter is the one
    mechanism that may not do this.
    """
    node = node_for(t)
    form = node.form
    children = node.children

    if form is TypeForm.ANY:
        return _ok(val, t, location)

    if form is TypeForm.NONE:
        if val is None:
            return _ok(val, t, location)
        return _bad(val, t, location, Detail.NOT_NONE)

    if form is TypeForm.CLASS or form is TypeForm.PROTOCOL:
        if isinstance(val, _isinstance_target(node)):
            return _ok(val, t, location)
        return _bad(val, t, location, Detail.NOT_AN_INSTANCE)

    if form in _WRAPPERS:
        frame = _ok(val, t, location)
        if children:
            frame.todo.append((val, children[0].t, Location(Place.WRAPPED)))
        return frame

    if form is TypeForm.UNION:
        frame = _ok(val, t, location)
        frame.is_union = True
        for i, child in enumerate(children):
            frame.todo.append((val, child.t, Location(Place.MEMBER, i)))
        return frame

    if form is TypeForm.LITERAL:
        val_t = type(val)
        for literal in typing.get_args(t):
            if literal is val or (type(literal) is val_t and literal == val):
                return _ok(val, t, location)
        return _bad(val, t, location, Detail.NO_LITERAL)

    if form is TypeForm.COLLECTION:
        origin = typing.get_origin(t)
        if not isinstance(val, origin):
            return _bad(val, t, location, Detail.NOT_AN_INSTANCE)
        frame = _ok(val, t, location)
        if children:
            # For an unordered collection the index is a position in iteration
            # order and is not stable across runs, so it is marked as such rather
            # than implying an addressable location.
            place = (
                Place.INDEX
                if isinstance(val, (list, tuple, str, bytes))
                else Place.POSITION
            )
            for i, item in enumerate(val):
                frame.todo.append((item, children[0].t, Location(place, i)))
        return frame

    if form is TypeForm.MAPPING:
        origin = typing.get_origin(t)
        if not isinstance(val, origin):
            return _bad(val, t, location, Detail.NOT_AN_INSTANCE)
        frame = _ok(val, t, location)
        if children:
            for key, item in val.items():
                frame.todo.append(
                    (key, children[0].t, Location(Place.KEY, key))
                )
                frame.todo.append(
                    (item, children[1].t, Location(Place.VALUE_AT, key))
                )
        return frame

    if form is TypeForm.TUPLE:
        return _expand_tuple(val, t, location, node)

    if form is TypeForm.TYPED_DICT:
        return _expand_typed_dict(val, t, location, node)

    if form is TypeForm.NAMED_TUPLE:
        if not isinstance(val, t):
            return _bad(val, t, location, Detail.NOT_AN_INSTANCE)
        frame = _ok(val, t, location)
        labels = node.labels or ()
        for name, child in zip(labels, children):
            frame.todo.append(
                (getattr(val, name), child.t, Location(Place.FIELD, name))
            )
        return frame

    if form is TypeForm.ANY_NAMED_TUPLE:
        if isinstance(val, tuple) and hasattr(type(val), "_fields"):
            return _ok(val, t, location)
        return _bad(val, t, location, Detail.NOT_A_NAMED_TUPLE)

    if form is TypeForm.TYPE_OF:
        return _expand_type_of(val, t, location, node)

    if form is TypeForm.ITERATOR:
        if isinstance(val, typing.get_origin(t)):
            return _ok(val, t, location)
        return _bad(val, t, location, Detail.NOT_AN_INSTANCE)

    if form is TypeForm.MAYBE_ITEMS:
        origin = typing.get_origin(t)
        if not isinstance(val, origin):
            return _bad(val, t, location, Detail.NOT_AN_INSTANCE)
        frame = _ok(val, t, location)
        if children and isinstance(val, Collection):
            for i, item in enumerate(val):
                frame.todo.append(
                    (item, children[0].t, Location(Place.INDEX, i))
                )
        return frame

    if form is TypeForm.GENERIC_CLASS:
        if isinstance(val, typing.get_origin(t)):
            return _ok(val, t, location)
        return _bad(val, t, location, Detail.NOT_AN_INSTANCE)

    if form is TypeForm.PLUGIN:
        return _expand_plugin(val, t, location, node)

    # An unsupported type is not a failure to explain: the value was never in
    # question, and something upstream should have raised long before here.
    return _ok(val, t, location)


_WRAPPERS = frozenset(
    {
        TypeForm.ALIAS,
        TypeForm.ANNOTATED,
        TypeForm.NEW_TYPE,
        TypeForm.TYPE_VAR,
    }
)
"""
Forms that stand for another type without being transparent.

Each reports as itself and delegates the verdict to what it wraps, so a failure
says both — ``UserId``, and then the ``int`` it turned out not to be.
"""


def _isinstance_target(node: TypeNode, /) -> Any:
    t = node.t
    origin = typing.get_origin(t)
    return t if origin is None else origin


def _expand_tuple(
    val: Any, t: Any, location: Location | None, node: TypeNode, /
) -> _Frame:
    if not isinstance(val, tuple):
        return _bad(val, t, location, Detail.NOT_AN_INSTANCE)
    args = typing.get_args(t)
    if not args:
        if t is typing.Tuple or not val:
            return _ok(val, t, location)
        return _bad(val, t, location, Detail.WRONG_LENGTH)
    frame = _ok(val, t, location)
    if len(args) == 2 and args[1] is Ellipsis:
        for i, item in enumerate(val):
            frame.todo.append(
                (item, node.children[0].t, Location(Place.INDEX, i))
            )
        return frame
    if len(val) != len(args):
        return _bad(val, t, location, Detail.WRONG_LENGTH)
    for i, (item, child) in enumerate(zip(val, node.children)):
        frame.todo.append((item, child.t, Location(Place.INDEX, i)))
    return frame


def _expand_typed_dict(
    val: Any, t: Any, location: Location | None, node: TypeNode, /
) -> _Frame:
    if not isinstance(val, Mapping):
        return _bad(val, t, location, Detail.NOT_AN_INSTANCE)
    for key in t.__required_keys__:
        if key not in val:
            return _bad(
                val,
                t,
                Location(Place.FIELD, key) if location is None else location,
                Detail.MISSING_KEY,
            )
    fields = dict(zip(node.labels or (), node.children))
    frame = _ok(val, t, location)
    for key, item in val.items():
        if not isinstance(key, str):
            return _bad(val, t, location, Detail.NON_STRING_KEY)
        child = fields.get(key)
        if child is None:
            continue
        frame.todo.append((item, child.t, Location(Place.FIELD, key)))
    return frame


def _expand_type_of(
    val: Any, t: Any, location: Location | None, node: TypeNode, /
) -> _Frame:
    if not isinstance(val, type):
        return _bad(val, t, location, Detail.NOT_A_CLASS)
    args = typing.get_args(t)
    if not args:
        return _ok(val, t, location)
    (arg,) = args
    if arg is Any:
        return _ok(val, t, location)
    target = arg.__args__ if type(arg) is Union else arg  # type: ignore[comparison-overlap]
    if issubclass(val, target):
        return _ok(val, t, location)
    return _bad(val, t, location, Detail.NOT_A_SUBCLASS)


def _expand_plugin(
    val: Any, t: Any, location: Location | None, node: TypeNode, /
) -> _Frame:
    origin = typing.get_origin(t)
    if not isinstance(val, origin):
        return _bad(val, t, location, Detail.NOT_AN_INSTANCE)
    check = getattr(origin, "__validate__", None)
    if check is None:
        from .plugins import registered_validator

        check = registered_validator(origin)
    if check is not None and check(val, typing.get_args(t)):
        return _ok(val, t, location)
    # A plugin's obligation is a boolean, so this is all there is to say unless
    # it chooses to say more. Diagnostics are an optional thing a plugin may
    # supply, not a toll for supporting one type.
    return _bad(val, t, location, Detail.PLUGIN_REJECTED)
