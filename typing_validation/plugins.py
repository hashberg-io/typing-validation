# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The extension point: how a parametrised class declares the way its type
arguments are validated.

The hook needs no machinery of its own, because the dispatch point already
exists. It is the generic-class arm — the one reached when a parametrised
type's origin is a plain class the core knows nothing about — which is
precisely where the core has run out of things it can determine on its own.

It is also free. ``int``, ``list[int]``, ``dict[str, int]``, unions and literals
all resolve long before that arm, so nothing that is not *already* unknown pays
anything for its existence.
"""

from collections.abc import Callable, Sequence
from typing import Any

from . import _cache as cache

__all__ = (
    "plugin_import",
    "register_validator",
    "registered_components",
    "registered_validator",
    "unsupported_explanation",
)

type PluginCheck = Callable[[Any, Sequence[Any]], bool]
"""
What a plugin must provide: given a value and the type arguments, say whether
the value is valid. Nothing more is required.

Asking every plugin author to also emit source for the compiled path would be an
absurd toll for supporting one type. A plugin may *optionally* supply more —
structure, diagnostics, an emitter — but a boolean is the whole obligation.
"""

type PluginComponents = Sequence[int]
"""
Optional: which of a parametrised class's type arguments the **core** validates,
by position.

Not every type argument is one, and ``numpy.ndarray[shape, dtype]`` has one of
each. The shape is an ordinary type, which the core checks the array's
``.shape`` tuple against. ``numpy.dtype[numpy.uint8]`` is a *specification the
plugin interprets*, and never a validation target in its own right — so NumPy
declares ``(0,)``.

The core cannot tell them apart, and guessing wrong is not harmless. Treating
every argument as a component makes ``numpy.dtype[numpy.uint8]`` one — and it is
itself a parametrised NumPy class with no validator of its own, so totality
poisons it, and with it every array type there is. Declaring components is what
keeps totality propagating through the arguments that deserve it and out of the
ones that do not.

Absent this, a plugin's arguments are opaque: the plugin checks them, and
totality does not reach inside.
"""

_REGISTRY: dict[type, PluginCheck] = {}
"""
Validators registered for classes we do not own.

A dunder classmethod is the ergonomic path for a class you own, but it is not
available for ``numpy.ndarray``, which we cannot give a dunder to. Neither
flavour subsumes the other.
"""

_COMPONENTS: dict[type, tuple[int, ...]] = {}
"""Component declarations, for the plugins that supply one."""

_PLUGINS = {"numpy": "typing_validation.numpy"}
"""
The modules this distribution ships a plugin for, and the import that enables
each.

Keyed by the first component of the origin's module name, which is a plain
string comparison requiring no import at all.

This table **decides behaviour**, and is the only thing that can. An
unregistered parametrised class is two different situations that arrive at the
same arm, and they must not be treated alike:

- ``mylib.Matrix[int]`` — nothing can determine the arguments of a class we
  know nothing about, so the type validates on its origin alone and the
  arguments go unchecked. That is the specified meaning, not a shortfall.
- ``numpy.ndarray[shape, dtype]`` — the arguments *are* determinable, by a
  plugin that ships right here and was not imported. Validating on the origin
  alone would report success it had not earned: ``validate(np.array([1.5]),
  NDArray[np.uint8])`` would pass. That is a totality violation, and it must be
  an error instead.

So an entry here is a claim that support exists and merely needs enabling, and
a missing entry costs correctness rather than helpfulness. The table is ours
for now; letting plugins contribute entries is an obvious extension, and
deliberately deferred.
"""


def register_validator(
    cls: type,
    check: PluginCheck,
    /,
    components: PluginComponents | None = None,
) -> None:
    """
    Declare how the type arguments of a parametrised class are validated.

    This is the route for classes you do not own. For a class you do own, define
    a ``__validate__`` classmethod instead, and a ``__validate_components__``
    class attribute if you want components::

        class Box[T]:
            __validate_components__ = (0,)

            @classmethod
            def __validate__(cls, val, args):
                return is_valid(val.item, args[0])

    ``cls`` is the class unparametrised — ``numpy.ndarray``, not
    ``numpy.ndarray[shape, dtype]``. ``components`` says which type arguments
    the core validates, **by position**, so that totality propagates through
    them; see :data:`~typing_validation.plugins.PluginComponents` for why the
    core cannot work that out for itself.

    :raises TypeError: if ``cls`` is not a class, ``check`` is not callable, or
        ``components`` is not a sequence of positions.
    """
    if not isinstance(cls, type):
        raise TypeError(f"Expected a class, got {cls!r}.")
    if not callable(check):
        raise TypeError(f"Expected a callable, got {check!r}.")
    _REGISTRY[cls] = check
    if components is not None:
        _COMPONENTS[cls] = _positions(components)
    _invalidate_nodes()


def _positions(components: PluginComponents, /) -> tuple[int, ...]:
    """
    Component positions, checked.

    Positions rather than a function that picks the types out, because every
    real case *is* a selection — NumPy's whole declaration is "the first one" —
    and a function could return types that appear nowhere in the type it
    describes, which would make ``inspect_type`` report children the type does
    not have.
    """
    try:
        positions = tuple(int(i) for i in components)
    except TypeError as exc:
        raise TypeError(
            f"Expected a sequence of argument positions, got {components!r}."
        ) from exc
    if any(i < 0 for i in positions):
        raise TypeError(
            f"Argument positions must not be negative: {positions}."
        )
    return positions


def _invalidate_nodes() -> None:
    """
    Drop every interned node, because registering has changed what is supported.

    Not housekeeping — this is what keeps the invariant that **interning is
    never semantically observable**. A node interned before registration records
    the type as unsupported, and would go on saying so afterwards, while a cold
    cache said otherwise. The verdict would then depend on whether anything had
    happened to ask first: ``can_validate(NDArray[np.uint8])`` answers
    :obj:`False` before ``import typing_validation.numpy`` and must answer
    :obj:`True` after, cache or no cache.

    Clearing everything is heavy-handed and exactly right. Registration happens
    at import time and approximately never after, so the cost is nil, and
    working out precisely which nodes a new validator affects means walking the
    whole graph anyway.
    """
    cache.clear()


def registered_validator(cls: type, /) -> PluginCheck | None:
    """
    The validator registered for a class, or :obj:`None` if there is none.
    """
    return _REGISTRY.get(cls)


def registered_components(cls: type, /) -> tuple[int, ...] | None:
    """
    Which of a class's type arguments the core validates, by position, or
    :obj:`None` if it declared none.
    """
    declared = _COMPONENTS.get(cls)
    if declared is not None:
        return declared
    own = getattr(cls, "__validate_components__", None)
    return None if own is None else _positions(own)


def plugin_import(origin: Any, /) -> str | None:
    """
    The import that would enable this distribution's plugin for a class, or
    :obj:`None` if we ship no plugin for it.

    A class we ship a plugin for is one whose arguments *are* checkable, so
    leaving them unchecked would report success we had not earned. Answering
    non-:obj:`None` here is therefore what turns an unregistered parametrised
    class from *"arguments unchecked, by design"* into an error.
    """
    module = getattr(origin, "__module__", "")
    return _PLUGINS.get(module.split(".")[0])


def unsupported_explanation(origin: Any, /) -> str:
    """
    Why a parametrised class could not be validated, and what would fix it.
    """
    # Every unsupported-generic error should teach: v1's flat "Unsupported
    # validation for type X" left the reader with nowhere to go.
    module = getattr(origin, "__module__", "")
    qualname = getattr(origin, "__qualname__", repr(origin))
    name = f"{module}.{qualname}" if module else qualname
    lines = [f"No validator is registered for generic class {name!r}."]
    enabling_import = plugin_import(origin)
    if enabling_import is not None:
        lines.append(
            f"Support is available but not enabled: "
            f"use 'import {enabling_import}'."
        )
    else:
        lines.append(
            "Define a '__validate__' classmethod on the class, or register a "
            "validator via typing_validation.register_validator(...)."
        )
    return "\n".join(lines)
