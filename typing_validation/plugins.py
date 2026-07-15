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

__all__ = (
    "plugin_import",
    "register_validator",
    "registered_validator",
    "unsupported_explanation",
)

PluginCheck = Callable[[Any, Sequence[Any]], bool]
"""
What a plugin must provide: given a value and the type arguments, say whether
the value is valid. Nothing more is required.

Asking every plugin author to also emit source for the compiled path would be an
absurd toll for supporting one type. A plugin may *optionally* supply more —
structure, diagnostics, an emitter — but a boolean is the whole obligation.
"""

_REGISTRY: dict[type, PluginCheck] = {}
"""
Validators registered for classes we do not own.

A dunder classmethod is the ergonomic path for a class you own, but it is not
available for ``numpy.ndarray``, which we cannot give a dunder to. Neither
flavour subsumes the other.
"""

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


def register_validator(cls: type, check: PluginCheck, /) -> None:
    """
    Declare how the type arguments of a parametrised class are validated.

    This is the route for classes you do not own. For a class you do own, define
    a ``__validate__`` classmethod instead, which takes the same arguments and
    means the same thing.

    :param cls: the class, unparametrised — ``numpy.ndarray``, not
        ``numpy.ndarray[shape, dtype]``.
    :param check: given a value and the type arguments, whether the value is
        valid.
    :raises TypeError: if ``cls`` is not a class, or ``check`` is not callable.
    """
    if not isinstance(cls, type):
        raise TypeError(f"Expected a class, got {cls!r}.")
    if not callable(check):
        raise TypeError(f"Expected a callable, got {check!r}.")
    _REGISTRY[cls] = check


def registered_validator(cls: type, /) -> PluginCheck | None:
    """
    The validator registered for a class, or :obj:`None` if there is none.

    :param cls: the unparametrised class.
    """
    return _REGISTRY.get(cls)


def plugin_import(origin: Any, /) -> str | None:
    """
    The import that would enable this distribution's plugin for a class, or
    :obj:`None` if we ship no plugin for it.

    A class we ship a plugin for is one whose arguments *are* checkable, so
    leaving them unchecked would report success we had not earned. Answering
    non-:obj:`None` here is therefore what turns an unregistered parametrised
    class from *"arguments unchecked, by design"* into an error.

    :param origin: the unparametrised class.
    """
    module = getattr(origin, "__module__", "")
    return _PLUGINS.get(module.split(".")[0])


def unsupported_explanation(origin: Any, /) -> str:
    """
    Why a parametrised class could not be validated, and what would fix it.

    Every unsupported-generic error should teach, which v1's flat *"Unsupported
    validation for type X"* never did.

    :param origin: the unparametrised class that has no validator.
    """
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
