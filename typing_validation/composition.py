# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Building a validation function specialised to one fixed type, by composing a
closure per node of the interned graph.

Construction is cheap and **structurally shared**: nodes are interned on the type
itself, so ``list[int]`` is analysed once and its closure reused everywhere it
occurs — inside ``dict[str, list[int]]``, inside ``tuple[list[int], ...]``, and
inside anything else mentioning it. The result is a graph over distinct
sub-types, not a tree over syntactic occurrences.

The shape here is chosen by measurement, and it is not the obvious one. Composing
closures that simply call one another is the obvious one, and it is 3x faster
than the interpreter per node — but it recurses once per level of the *value*,
so it raises :class:`RecursionError` on exactly the deeply nested values the
interpreter goes out of its way to handle. Two mechanisms disagreeing about one
value, one of them by crashing, is what the architecture exists to prevent.
Composing closures that all push onto a shared work stack fixes that, and is only
1.16x faster, which does not earn a second mechanism at all.

**Depth grows only where a check can descend.** A check that answers from the
value alone cannot grow the stack, so calling it directly costs one call and
risks nothing. So a container *calls* the children that cannot descend and
*pushes* the ones that can. On ``list[int]`` that is the fast shape, at 2.9x the
interpreter; on a recursive alias it is the safe one.
"""

from collections.abc import Callable, Collection, Iterator, Mapping
from typing import Any, Literal, Union, get_args, get_origin

from .diagnosis import diagnose
from .errors import UnsupportedTypeError, ValidationError
from .nodes import TypeForm, TypeNode, node_for
from .plugins import registered_validator

__all__ = ("validator",)

type Stack = list[tuple[Any, "Check"]]
type Unions = list[list[Any]]
type Check = Callable[[Any, Stack, Unions], bool]
"""
One node's composed check: given a value, the work stack and the union
bookkeeping, whether the value is valid *here*, having pushed whatever remains.

Every check takes all three whether it uses them or not. A check that cannot
descend ignores both, which costs two unused arguments and saves the wrapper that
dropping them would need.
"""

type Composed = tuple[Check, bool]
"""
A check, and whether it can push.

The second is what decides call-versus-push at every parent, and it is a property
of the *check* rather than of the node's children: a union of plain classes has
children and still collapses to a single ``isinstance``, so it can no more
descend than ``int`` can.
"""


def validator(t: Any, /) -> Callable[[Any], Literal[True]]:
    """
    A validation function specialised to one type.

    Same contract as :func:`~typing_validation.validation.validate`, and the same
    verdict on every value. It pays for itself when the same type is validated
    repeatedly, because it analyses the type once rather than once per value::

        check = validator(list[int])
        for payload in payloads:
            check(payload)

    Unlike :func:`~typing_validation.validation.validate`, this refuses an
    unsupported type **immediately** rather than when a value happens to reach the
    unsupported part. It has to: it analyses the whole type before it sees any
    value. So ``validator(list[Callable[[int], int]])`` raises here, where
    ``validate([], list[Callable[[int], int]])`` returns :obj:`True`.

    :raises UnsupportedTypeError: if the type, or any component of it, is not one
        this library can validate against.
    """
    node = node_for(t)
    if not node.supported:
        culprits = node.unsupported_components()
        raise UnsupportedTypeError(t, culprits[0].reason if culprits else None)
    check, _ = _composed(node)

    def run(val: Any) -> Literal[True]:
        if _drive(val, check):
            return True
        raise ValidationError(val, t, diagnose(val, t))

    return run


def _drive(val: Any, root: Check, /) -> bool:
    """
    Run a composed check to completion.

    The same loop the interpreter runs, and for the same reasons — it is a loop
    so that the depth of the *value* cannot overflow anything, and unions are
    flag-gated so that a failing member is a boolean rather than an exception.
    What differs is that no dispatch happens here: each check was chosen when the
    type was analysed, so the loop only calls what it is handed.
    """
    stack: Stack = []
    unions: Unions = []
    if not root(val, stack, unions):
        if not _backtrack(stack, unions):
            return False
    while True:
        while unions and len(stack) == unions[-1][2]:
            unions.pop()
        if not stack:
            return True
        item, check = stack.pop()
        if check(item, stack, unions):
            continue
        if not _backtrack(stack, unions):
            return False


def _backtrack(stack: Stack, unions: Unions, /) -> bool:
    """
    Move to the next member of the innermost union attempt, if there is one.

    Discarding the failed attempt's leftovers is sound only because validation is
    pure: a member that failed part-way leaves nothing behind for the next.
    """
    while unions:
        val, members, depth, index = unions[-1]
        if index < len(members):
            del stack[depth:]
            unions[-1][3] = index + 1
            stack.append((val, members[index]))
            return True
        unions.pop()
    return False


def _composed(node: TypeNode, /) -> Composed:
    """
    Compose a check for every node reachable from this one, children first.

    Iterative, for the reason everything here is: ``list[list[...[int]]]``
    nested thousands deep recurses nowhere and would still overflow a recursive
    compositor.

    Children are composed before parents, so a parent finds its children ready —
    **except across a back-edge**, where the child is an ancestor still being
    composed. Those, and only those, are late-bound: the closure reads the node's
    slot when called rather than capturing one that does not exist yet. One
    indirection, paid at the cycle and nowhere else.
    """
    building: set[int] = set()
    todo: list[tuple[TypeNode, bool]] = [(node, False)]
    while todo:
        current, ready = todo.pop()
        if current._check is not None:
            continue
        if ready:
            building.discard(id(current))
            current._check, current._can_push = _compose(current)
            continue
        if id(current) in building:
            continue
        building.add(id(current))
        todo.append((current, True))
        for child in reversed(current.children):
            if child._check is None and id(child) not in building:
                todo.append((child, False))
    check = node._check
    assert check is not None
    return check, node._can_push


def _children_of(node: TypeNode, /) -> list[Composed]:
    """Each child's check, and whether it must be pushed rather than called."""
    return [_bind(child) for child in node.children]


def _bind(node: TypeNode, /) -> Composed:
    """
    A node's check, late-bound if it is not composed yet.

    Not composed yet means this is a back-edge: the node is an ancestor of the
    one asking, still being built. Reading the slot at call time is what lets the
    cycle close — and such a node is assumed to be able to push, which is both
    conservative and true, since a cycle is precisely where depth is unbounded.
    """
    check = node._check
    if check is not None:
        return check, node._can_push

    def late(val: Any, stack: Stack, unions: Unions) -> bool:
        composed: Check = node._check
        return composed(val, stack, unions)

    return late, True


def _descend(child: Composed, /) -> Callable[[Any, Stack, Unions], bool]:
    """
    How a parent reaches one child: by calling it, or by pushing it.

    This is the whole design in one function. A child that cannot push cannot
    descend, so calling it can neither overflow the stack nor lose work; a child
    that can push must go through the stack, or the Python frames would grow with
    the depth of the value.
    """
    check, can_push = child
    if not can_push:
        return check

    def push(val: Any, stack: Stack, unions: Unions) -> bool:
        stack.append((val, check))
        return True

    return push


def _compose(node: TypeNode, /) -> Composed:
    """
    The check for one node, closed over its children's, and whether it can push.

    This duplicates the interpreter's semantics deliberately: the two answer to
    the catalogue rather than to each other, and the conformance suite is what
    keeps them agreeing. What differs is *when* the decisions are made. Every arm
    the interpreter picks per value — the form, the origin, the arguments, the
    required keys — is picked here, once, and what survives into the closure is
    only the work.
    """
    form = node.form
    t = node.t
    if form is TypeForm.ANY:
        return _any, False
    if form is TypeForm.NONE:
        return _none, False
    if form is TypeForm.CLASS or form is TypeForm.PROTOCOL:
        return _instance_of(_isinstance_target(node)), False
    if form is TypeForm.ITERATOR:
        # Its items cannot be checked without consuming it, and purity forbids
        # that, so there is nothing to descend into.
        return _instance_of(get_origin(t)), False
    if form is TypeForm.GENERIC_CLASS:
        return _instance_of(get_origin(t)), False
    if form is TypeForm.ANY_NAMED_TUPLE:
        return _any_named_tuple, False
    if form is TypeForm.LITERAL:
        return _literal(get_args(t)), False
    if form is TypeForm.TYPE_OF:
        return _type_of(get_args(t)), False
    if form is TypeForm.PLUGIN:
        return _plugin(t), False
    if form in _WRAPPERS:
        # An alias, Annotated, NewType or bounded type variable stands for its
        # child and inherits everything about it, including whether it descends.
        if not node.children:
            return _any, False
        return _children_of(node)[0]
    if form is TypeForm.UNION:
        return _union(node)
    if form is TypeForm.COLLECTION:
        return _collection(get_origin(t), node)
    if form is TypeForm.MAPPING:
        return _mapping(get_origin(t), node)
    if form is TypeForm.TUPLE:
        return _tuple(get_args(t), node)
    if form is TypeForm.TYPED_DICT:
        return _typed_dict(t, node)
    if form is TypeForm.NAMED_TUPLE:
        return _named_tuple(t, node)
    if form is TypeForm.MAYBE_ITEMS:
        return _maybe_items(get_origin(t), node)
    raise UnsupportedTypeError(t, node.reason)


_WRAPPERS = frozenset(
    {TypeForm.ALIAS, TypeForm.ANNOTATED, TypeForm.NEW_TYPE, TypeForm.TYPE_VAR}
)


def _isinstance_target(node: TypeNode, /) -> Any:
    origin = get_origin(node.t)
    return node.t if origin is None else origin


def _any(val: Any, stack: Stack, unions: Unions) -> bool:
    return True


def _none(val: Any, stack: Stack, unions: Unions) -> bool:
    return val is None


def _any_named_tuple(val: Any, stack: Stack, unions: Unions) -> bool:
    return isinstance(val, tuple) and hasattr(type(val), "_fields")


def _instance_of(cls: Any, /) -> Check:
    def check(val: Any, stack: Stack, unions: Unions) -> bool:
        return isinstance(val, cls)

    return check


def _literal(literals: tuple[Any, ...], /) -> Check:
    def check(val: Any, stack: Stack, unions: Unions) -> bool:
        val_t = type(val)
        for literal in literals:
            if literal is val or (type(literal) is val_t and literal == val):
                return True
        return False

    return check


def _type_of(args: tuple[Any, ...], /) -> Check:
    if not args or args[0] is Any:
        return _instance_of(type)
    (arg,) = args
    target = arg.__args__ if type(arg) is Union else arg  # type: ignore[comparison-overlap]

    def check(val: Any, stack: Stack, unions: Unions) -> bool:
        return isinstance(val, type) and issubclass(val, target)

    return check


def _plugin(t: Any, /) -> Check:
    origin = get_origin(t)
    args = get_args(t)
    plugin = getattr(origin, "__validate__", None)
    if plugin is None:
        plugin = registered_validator(origin)
    assert plugin is not None

    def check(val: Any, stack: Stack, unions: Unions) -> bool:
        return isinstance(val, origin) and bool(plugin(val, args))

    return check


def _union(node: TypeNode, /) -> Composed:
    """
    Valid if at least one member is.

    Members that are all plain classes collapse to a single ``isinstance``
    against the argument tuple — ``int | None``, ``str | bytes``,
    ``int | str | None``, the overwhelmingly common shapes — which cannot descend
    and so is a check a parent may call rather than push. The whole apparatus
    below exists for the rest.
    """
    members = node.t.__args__
    if all(type(member) is type for member in members):
        return _instance_of(members), False
    checks = tuple(_bind(child)[0] for child in node.children)

    def check(val: Any, stack: Stack, unions: Unions) -> bool:
        # A member attempt is the unit of success: given list[int] | list[str]
        # and [1, "a"], the 1 matching int must not settle the union, because the
        # attempt is not finished. The recorded depth is what delimits it.
        unions.append([val, checks, len(stack), 1])
        stack.append((val, checks[0]))
        return True

    return check, True


def _collection(origin: Any, node: TypeNode, /) -> Composed:
    if not node.children:
        return _instance_of(origin), False
    item = _descend(_children_of(node)[0])

    def check(val: Any, stack: Stack, unions: Unions) -> bool:
        if not isinstance(val, origin):
            return False
        for x in val:
            if not item(x, stack, unions):
                return False
        return True

    return check, True


def _mapping(origin: Any, node: TypeNode, /) -> Composed:
    if not node.children:
        return _instance_of(origin), False
    key, value = (_descend(c) for c in _children_of(node))

    def check(val: Any, stack: Stack, unions: Unions) -> bool:
        if not isinstance(val, origin):
            return False
        for k, v in val.items():
            if not key(k, stack, unions):
                return False
            if not value(v, stack, unions):
                return False
        return True

    return check, True


def _tuple(args: tuple[Any, ...], node: TypeNode, /) -> Composed:
    if not args:
        # tuple[()] is the empty tuple. Bare typing.Tuple never arrives here: the
        # node model classifies it as a class.
        def check_empty(val: Any, stack: Stack, unions: Unions) -> bool:
            return isinstance(val, tuple) and not val

        return check_empty, False
    if len(args) == 2 and args[1] is Ellipsis:
        item = _descend(_children_of(node)[0])

        def check_variadic(val: Any, stack: Stack, unions: Unions) -> bool:
            if not isinstance(val, tuple):
                return False
            for x in val:
                if not item(x, stack, unions):
                    return False
            return True

        return check_variadic, True
    items = tuple(_descend(c) for c in _children_of(node))
    size = len(items)

    def check_fixed(val: Any, stack: Stack, unions: Unions) -> bool:
        if not isinstance(val, tuple) or len(val) != size:
            return False
        for x, item_check in zip(val, items):
            if not item_check(x, stack, unions):
                return False
        return True

    return check_fixed, True


def _typed_dict(t: Any, node: TypeNode, /) -> Composed:
    required = frozenset(t.__required_keys__)
    fields = dict(
        zip(node.labels or (), (_descend(c) for c in _children_of(node)))
    )

    def check(val: Any, stack: Stack, unions: Unions) -> bool:
        if not isinstance(val, Mapping):
            return False
        for key in required:
            if key not in val:
                return False
        for key, item in val.items():
            if not isinstance(key, str):
                return False
            field = fields.get(key)
            if field is not None and not field(item, stack, unions):
                return False
        return True

    return check, True


def _named_tuple(t: Any, node: TypeNode, /) -> Composed:
    fields = tuple(
        zip(node.labels or (), (_descend(c) for c in _children_of(node)))
    )

    def check(val: Any, stack: Stack, unions: Unions) -> bool:
        if not isinstance(val, t):
            return False
        for name, field in fields:
            if not field(getattr(val, name), stack, unions):
                return False
        return True

    return check, True


def _maybe_items(origin: Any, node: TypeNode, /) -> Composed:
    if not node.children:
        return _instance_of(origin), False
    item = _descend(_children_of(node)[0])

    def check(val: Any, stack: Stack, unions: Unions) -> bool:
        if not isinstance(val, origin):
            return False
        if not isinstance(val, Collection):
            # Potentially one-shot, so its items cannot be checked without
            # consuming it. Same rule as an iterator, for the same reason.
            return True
        for x in val:
            if not item(x, stack, unions):
                return False
        return True

    return check, True
