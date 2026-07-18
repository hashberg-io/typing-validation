# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Rendering caller-supplied objects into messages, without trusting them.

Every value and every type in a message came from the caller, and either can
raise from its own ``__repr__``. That is not a contrived object: a class whose
``__repr__`` reads attributes will raise from inside ``__init__`` until the last
of them is assigned, which is precisely where a caller is most likely to be
validating ``self``.

An error message is the worst place to discover this. The exception it raises
replaces the diagnosis with a traceback into the caller's own ``__repr__``,
displacing the failure the message existed to report — the library is then
unusable for exactly the debugging it was reached for.

So nothing here calls ``repr`` or ``str`` on a caller's object unguarded, and a
module that no other part of the package imports is where that guarantee is kept
whole rather than re-derived at each site.
"""

from typing import Any

__all__ = ("safe_repr", "safe_str")


def _fallback(obj: Any, exc: BaseException, /) -> str:
    """
    What to show once the object has refused to describe itself.

    Says three things, because a reader who has just lost the repr they expected
    needs all of them: what the object is, which one it is, and that the blank is
    the object's own doing rather than this library's.
    """
    try:
        name = type(obj).__name__
    except Exception:
        name = "object"
    return (
        f"<{name} object at {id(obj):#x}; __repr__ raised {type(exc).__name__}>"
    )


def safe_repr(obj: Any, /) -> str:
    """
    ``repr(obj)``, or a description of it if that raises.

    Catches :class:`BaseException` rather than :class:`Exception`, because the
    point is that the message survives whatever the object does, and a
    ``__repr__`` that raises :class:`KeyboardInterrupt` is a broken ``__repr__``
    like any other. The one it must not swallow is a failure to build the
    fallback, which is this library's bug and not the caller's.
    """
    try:
        return repr(obj)
    except BaseException as exc:
        return _fallback(obj, exc)


def safe_str(obj: Any, /) -> str:
    """
    ``str(obj)``, or a description of it if that raises.

    Types reach messages through :func:`str` rather than :func:`repr`, and a type
    is as capable of raising as a value: a class whose metaclass defines
    ``__str__`` gets whatever that metaclass does.
    """
    try:
        return str(obj)
    except BaseException as exc:
        return _fallback(obj, exc)
