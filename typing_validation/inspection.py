# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Asking about a type, rather than about a value: what it is, whether it can be
validated against, and — when it cannot — precisely what stopped it.

In v1 this was a side effect of a validation walk, obtained by passing an
inspector *as the value* into ``validate`` and having every branch record itself
instead of checking. One walk served two purposes, and every new type form had to
be implemented three times in lockstep. Here the structure is a real artifact,
built from the node model, which exists anyway.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from . import cache
from .nodes import TypeNode, node_for

__all__ = (
    "can_validate",
    "clear_cache",
    "forget_type",
    "inspect_type",
    "scoped_cache",
)


def inspect_type(t: Any, /) -> TypeNode:
    """
    The structure of a type: its shape, its components, and whether each is
    supported.

    When a type is unsupported this reports the **whole** structure and marks
    precisely which component poisoned it. Totality means the answer to *"can
    this be validated"* is then always "no", but it should never be an opaque
    "no" — use :meth:`~typing_validation.nodes.TypeNode.unsupported_components`
    to name the culprits.
    """
    return node_for(t)


def can_validate(t: Any, /) -> bool:
    """
    Whether this library can validate against a type at all.

    Support is all-or-nothing: ``tuple[int, Callable[[int], int]]`` answers
    :obj:`False` even though the ``int`` component is perfectly checkable,
    because a validation that silently skipped part of its obligation would be
    worse than none. This function exists so a caller can ask up front.

    Note that :func:`~typing_validation.validate` is *lazier* than this. It walks
    the value and the type together and raises only when it reaches an
    unsupported component, so ``validate([], list[Callable[[int], int]])``
    returns :obj:`True` while this returns :obj:`False`. That is deliberate:
    scanning the type on every call is exactly the overhead that mechanism exists
    to avoid. This is the total answer, and it is the one to branch on.
    """
    return node_for(t).supported


def clear_cache() -> None:
    """
    Drop every interned node.

    Safe by construction: interning is never semantically observable, so this
    changes cost and never an answer. Without that guarantee, clearing a cache
    would be a semantic operation and no user could be expected to reason about
    it.
    """
    cache.clear()


def forget_type(t: Any, /) -> bool:
    """
    Drop the interned node for one type, if it has one.

    Returns whether anything was dropped. Note that nodes for its *components*
    are untouched and may still be shared by other types.
    """
    return cache.forget(t)


@contextmanager
def scoped_cache() -> Iterator[None]:
    """
    Intern nodes into a temporary tier, dropped whole on exit.

    For callers who want the sharing without the retention: a strong reference to
    a type transitively pins the classes it mentions, and through them their
    modules and closures, so a process that builds types dynamically — synthesised
    ``TypedDict``\\ s, classes from a factory, types built per request — would
    otherwise accumulate them forever.

    While the tier is active, lookups consult tiers innermost-first and every new
    node is created in the innermost tier. Exiting drops that tier in one
    operation, with no per-entry bookkeeping::

        with scoped_cache():
            validate(val, build_a_type())

    Nodes created inside may reference nodes in enclosing tiers, which outlive
    them; nothing enclosing can reference inward, because while this tier is
    active it is where all new nodes go. So dropping it can never leave a
    dangling reference — and can never change an answer, only a cost.
    """
    cache.push_tier()
    try:
        yield
    finally:
        cache.pop_tier()
