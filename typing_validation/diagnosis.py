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
may be as slow, allocating and thorough as it likes — where its costs stop
mattering and its quality is the entire point.

The second traversal is sound only because validation is pure: the value handed
here is the value the validator saw, undisturbed.
"""

# This is, in effect, v1's validate — rich and allocating — demoted from the hot
# path to diagnostics duty.

import enum
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from typing import (
    NewType,
    TypeAliasType,
    Any,
    final,
    get_args,
    get_origin,
    Literal,
    NamedTuple,
    Tuple,
    Union,
)
from .nodes import TypeForm, TypeNode, node_for
from .plugins import registered_validator

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
    """
    Where this sits within the value that contains it. :obj:`None` at the root.
    """

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
        """
        The failure as a message: what was expected, where, and in what.

        Three slots, of which the third is dropped when the first has already
        filled it::

            expected int, got str '1975'
              at:  value.year
              in:  Movie

        The tree records everything; the message reports the one place worth
        looking at. Which place that is takes some finding — see :func:`_locate`.
        """
        path, deepest = _locate(self)
        lines = [_says(deepest), f"  at:  value{path}"]
        # `in:` names the type the caller asked about. Line one has already
        # named it whenever the failure is at the root and the detail says
        # "expected <type>", so repeating it would add nothing. The details that
        # never name a type are exactly the ones that still need it.
        already_named = (
            self.t is deepest.t and deepest.detail not in _NAMELESS_DETAILS
        )
        if not already_named:
            lines.append(f"  in:  {_show(self.t)}")
        return "\n".join(lines)


# TODO: make the message's verbosity an option, once there is an option manager
# to hang it on. The tree records every level and the message reports one place,
# which is right by default and occasionally not: someone debugging a union that
# should have matched wants to see what each member objected to, and someone
# reading a deeply nested failure may want the containment chain rather than just
# its endpoint. That is a switch, not a rewrite — the tree already holds all of
# it, and this is the only place that decides what to show.


_NAMELESS_DETAILS = (Detail.MISSING_KEY, Detail.NON_STRING_KEY)
"""
The details whose message never names the type it is about.

Every other detail reads *"expected <type>"*, which is what makes ``in:``
redundant for a failure at the root. These two do not, so they keep it.
"""


def _show(t: Any, /) -> str:
    """
    A type as the user wrote it, rather than as Python reprs it.

    ``int`` rather than ``<class 'int'>``, and ``UserId`` rather than
    ``module.UserId``: the message is read by someone who has the type in front
    of them, and its module is noise.
    """
    if t is None or t is type(None):
        return "None"
    if isinstance(t, type):
        return t.__name__
    name = getattr(t, "__name__", None)
    if name is not None and type(t) in (TypeAliasType, NewType):
        return str(name)
    return str(t).replace("typing.", "")


def _plural(n: int, noun: str, /) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _says(f: ValidationFailure, /) -> str:
    """What went wrong, in one line, at the place worth looking at."""
    if f.detail is Detail.MISSING_KEY:
        return f"missing required key {f.location.at!r}"  # type: ignore[union-attr]
    if f.detail is Detail.NON_STRING_KEY:
        return f"keys must be strings, got {type(f.val).__name__}"
    if f.detail is Detail.WRONG_LENGTH:
        return f"expected {_show(f.t)}, got {_plural(len(f.val), 'element')}"
    if f.detail is Detail.NO_LITERAL:
        # A literal's own type is the point, so naming the value's type as well
        # would be saying the same thing twice. This is the one detail that does
        # not end in a type-and-value pair, deliberately.
        return f"expected {_show(f.t)}, got {f.val!r}"
    if f.detail is Detail.NOT_A_CLASS:
        return f"expected a class, got {type(f.val).__name__} {f.val!r}"
    if f.detail is Detail.NOT_A_NAMED_TUPLE:
        return f"expected a named tuple, got {type(f.val).__name__} {f.val!r}"
    return f"expected {_show(f.t)}, got {type(f.val).__name__} {f.val!r}"


def _step(f: ValidationFailure, /) -> str:
    """How to reach this failure from the value that contains it, in code."""
    if f.location is None:
        return ""
    place, at = f.location.place, f.location.at
    if place is Place.INDEX:
        return f"[{at}]"
    if place is Place.POSITION:
        # Braces rather than brackets, because iteration order is not stable
        # across runs: this is a witness that something failed, not an address
        # the reader can go to.
        return f"{{{at}}}"
    if place is Place.KEY:
        return f".keys(){{{at!r}}}"
    if place is Place.VALUE_AT:
        return f"[{at!r}]"
    if place is Place.FIELD:
        return f".{at}"
    return ""


def _locate(root: ValidationFailure, /) -> tuple[str, ValidationFailure]:
    """
    The deepest place in the value the failure reaches, and what was expected
    *there*.

    Two rules, and the naive walk gets both wrong.

    **Through a union, follow the member that got furthest.** A union fails only
    when every member fails, so listing them all says nothing the union type has
    not already said — and most of them fail on sight. Five of ``JSON``'s six
    members reject a dict immediately; only ``dict[str, JSON]`` gets deep enough
    to be worth reading, and it is the one that finds the offending float.

    **Report the type recorded at the deepest step**, not whatever the walk
    bottoms out in. An alias is not transparent, so at ``value['a'][1]['b']`` the
    answer is *"expected JSON"* — not the six-member union that ``JSON`` happens
    to expand to, which is longer and says less.
    """
    f, path, deepest = root, "", root
    while True:
        if f.detail is Detail.IN_COMPONENT and f.causes:
            child = f.causes[0]
            step = _step(child)
            f = child
            if step:
                path += step
                deepest = child
        elif f.detail is Detail.NO_UNION_MEMBER and f.causes:
            best = max(f.causes, key=lambda c: c.depth())
            if best.depth() <= 1:
                # Every member failed on sight, so there is nothing deeper to
                # report and the union itself is the answer.
                return path, deepest
            f = best
        else:
            return path, deepest


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
        for literal in get_args(t):
            if literal is val or (type(literal) is val_t and literal == val):
                return _ok(val, t, location)
        return _bad(val, t, location, Detail.NO_LITERAL)
    if form is TypeForm.COLLECTION:
        origin = get_origin(t)
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
        origin = get_origin(t)
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
        if isinstance(val, get_origin(t)):
            return _ok(val, t, location)
        return _bad(val, t, location, Detail.NOT_AN_INSTANCE)
    if form is TypeForm.MAYBE_ITEMS:
        origin = get_origin(t)
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
        if isinstance(val, get_origin(t)):
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
    origin = get_origin(t)
    return t if origin is None else origin


def _expand_tuple(
    val: Any, t: Any, location: Location | None, node: TypeNode, /
) -> _Frame:
    if not isinstance(val, tuple):
        return _bad(val, t, location, Detail.NOT_AN_INSTANCE)
    args = get_args(t)
    if not args:
        if t is Tuple or not val:
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
    args = get_args(t)
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
    origin = get_origin(t)
    if not isinstance(val, origin):
        return _bad(val, t, location, Detail.NOT_AN_INSTANCE)
    check = getattr(origin, "__validate__", None)
    if check is None:
        check = registered_validator(origin)
    if check is not None and check(val, get_args(t)):
        return _ok(val, t, location)
    # A plugin's obligation is a boolean, so this is all there is to say unless
    # it chooses to say more. Diagnostics are an optional thing a plugin may
    # supply, not a toll for supporting one type.
    return _bad(val, t, location, Detail.PLUGIN_REJECTED)
