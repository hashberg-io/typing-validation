# SPDX-License-Identifier: LGPL-3.0-or-later

"""Compatibility helpers for changes in Python's typing implementation."""

from typing import Any


def is_bytestring_origin(origin: Any, /) -> bool:
    """Recognize ``ByteString`` without importing its deprecated class.

    ``typing.ByteString`` is still accepted as an input type, but Python 3.15
    warns when either it or ``collections.abc.ByteString`` is accessed.  The
    typing form's origin is the latter class, so looking at its metadata lets
    us retain support without triggering a warning during library import or
    validation.  It is deliberately not compared with ``Buffer``: the two
    classes are distinct, even though ByteString is validated using Buffer's
    semantics here.
    """
    # Do not replace this with an import of either ByteString spelling.  Such
    # an import is precisely what raises DeprecationWarning on Python 3.15 and
    # will stop working when ByteString is removed in Python 3.17.
    return (
        getattr(origin, "__module__", None) == "collections.abc"
        and getattr(origin, "__qualname__", None) == "ByteString"
    )
