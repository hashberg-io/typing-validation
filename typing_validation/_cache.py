# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The intern cache: where analysed types are kept, and how they are dropped.

This sits **below** both the node model and the plugin registry, and imports
neither. That is what lets the registry invalidate the cache on registration
without a cycle: the module that stores the nodes owns the storage, and the
modules that fill it and that invalidate it both depend on it rather than on each
other.

By default the cache lives forever and holds strong references, because types are
usually module-level objects that outlive any cache anyway.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Only for the annotations: importing the node model for real would be the
    # very cycle this module exists below in order to avoid.
    from .nodes import TypeNode

__all__ = ()

_TIERS: list[dict[Any, "TypeNode"]] = [{}]
"""
The tiers, innermost last.

Scoped caching pushes a tier; lookups consult the tiers innermost-first; every
new node is created in the innermost tier; exiting drops that tier whole, in one
operation, with no per-entry bookkeeping.

The tiering is sound because **references only ever point outward**. A node
created while a tier is active lives in that tier and may reference nodes in
enclosing tiers, which outlive it. Nothing in an enclosing tier can reference into
an inner one, because while the inner tier is active it is where all new nodes go.
So dropping a tier can never leave a dangling reference behind it — and can never
change an answer, only a cost.
"""


def lookup(t: Any, /) -> "TypeNode | None":
    """
    The cached node for a type, innermost tier first, or :obj:`None`.

    Raises :class:`TypeError` for an unhashable type, which the caller takes as
    its signal to build an unshared node.
    """
    for tier in reversed(_TIERS):
        node = tier.get(t)
        if node is not None:
            return node
    return None


def store(t: Any, node: "TypeNode", /) -> None:
    """Put a node in the innermost tier."""
    _TIERS[-1][t] = node


def clear() -> None:
    """
    Drop every node.

    Safe by construction: interning is never semantically observable, so this
    changes cost and never an answer. Without that guarantee, clearing a cache
    would be a semantic operation and no user could be expected to reason about
    it.
    """
    for tier in _TIERS:
        tier.clear()


def forget(t: Any, /) -> bool:
    """Drop one type's node, reporting whether there was one."""
    dropped = False
    for tier in _TIERS:
        try:
            if tier.pop(t, None) is not None:
                dropped = True
        except TypeError:
            return False
    return dropped


def push_tier() -> None:
    """Start interning into a fresh, temporary tier."""
    _TIERS.append({})


def pop_tier() -> None:
    """Drop the innermost tier, whole."""
    _TIERS.pop()
