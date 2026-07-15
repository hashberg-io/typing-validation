# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Validation for NumPy array types: ``NDArray[dtype]`` and
``ndarray[shape, dtype]``.

**Import this module to enable it.** Without the import, NumPy array types raise
:class:`~typing_validation.UnsupportedTypeError`, and the error says so::

    import typing_validation.numpy

The tempting alternative — enabling automatically when NumPy happens to be
importable — is rejected on determinism grounds. It would make the supported
surface depend on transitive imports, so ``can_validate(NDArray[np.uint8])``
would answer :obj:`True` in a process where some unrelated dependency imported
NumPy and :obj:`False` in one where it did not. A predicate people branch on must
not behave that way, and the failure would be maddening to diagnose precisely
because nothing in the user's own code would have changed.

This is v1 functionality, moved out of the core. v1 wired an ``import numpy``
probe into the middle of the dispatcher, putting an optional third-party
dependency on the hot path of a library that has no dependencies. But the
stronger reason to move it is that it **dogfoods the plugin API**: a plugin
system whose author never uses it is always subtly wrong, and NumPy is a
punishing first client.
"""

from collections.abc import Sequence
from typing import (
    Any,
    get_args,
    get_origin,
    Union,
)
import numpy as np

from .errors import UnsupportedTypeError
from .plugins import register_validator
from .validation import is_valid

__all__ = ()


def _spelling(args: Sequence[Any], /) -> Any:
    """
    The array type these arguments came from, for an error to name.

    A plugin is handed the arguments rather than the type, so the type has to be
    reassembled to report it. Built via ``__class_getitem__`` because the static
    form would be a type annotation, and these are values.
    """
    return np.ndarray.__class_getitem__(tuple(args))


def _dtypes(spec: Any, t: Any, /) -> tuple[Any, ...]:
    """
    The scalar types a dtype specification admits, flattening unions.

    ``NDArray[np.uint8 | np.float32]`` is a union *inside* a plugin's argument,
    and the plugin is what understands it means "either dtype" rather than
    "a value valid for either type".
    """
    if spec is Any:
        return (Any,)
    if type(spec) is Union:  # type: ignore[comparison-overlap]
        return tuple(
            dtype for member in spec.__args__ for dtype in _dtypes(member, t)
        )
    if isinstance(spec, type) and issubclass(spec, np.generic):
        return (spec,)
    raise UnsupportedTypeError(
        t,
        f"Unsupported NumPy dtype {spec!r}. Expected a numpy scalar type, a "
        f"union of them, or Any.",
    )


def _unpack(args: Sequence[Any], t: Any, /) -> tuple[Any, Any]:
    """The shape type and the dtype specification of ``ndarray[shape, dtype]``."""
    if len(args) != 2:
        raise UnsupportedTypeError(
            t,
            "Expected numpy.ndarray[shape, dtype], such as "
            "NDArray[numpy.uint8].",
        )
    shape_t, dtype_container = args
    dtype_args = get_args(dtype_container)
    if get_origin(dtype_container) is not np.dtype or not dtype_args:
        raise UnsupportedTypeError(
            t,
            f"Expected numpy.dtype[...] as the second argument, got "
            f"{dtype_container!r}.",
        )
    return shape_t, dtype_args[0]


def _check_ndarray(val: Any, args: Sequence[Any], /) -> bool:
    """
    Whether an array matches a ``ndarray[shape, dtype]``.

    The dtype is the plugin's own business, checked with :func:`numpy.issubdtype`
    so that ``NDArray[np.integer]`` accepts a ``uint8`` array. The **shape** is
    not: it is an ordinary type, and the array's ``.shape`` is an ordinary tuple,
    so it is handed straight back to the core. ``NDArray[np.uint8]`` then means
    any shape, and ``ndarray[tuple[int, int], np.dtype[np.uint8]]`` means a
    matrix, with no shape logic here at all.
    """
    t = _spelling(args)
    shape_t, dtype_spec = _unpack(args, t)
    dtypes = _dtypes(dtype_spec, t)
    if not any(
        dtype is Any or np.issubdtype(val.dtype, dtype) for dtype in dtypes
    ):
        return False
    return is_valid(val.shape, shape_t)


def _ndarray_components(args: Sequence[Any], /) -> Sequence[Any]:
    """
    The shape type, and only the shape type.

    The dtype argument is a specification this plugin interprets, not a
    validation target: ``numpy.dtype[numpy.uint8]`` is itself a parametrised
    NumPy class with no validator, so calling it a component would poison every
    array type through totality.
    """
    return args[:1]


register_validator(np.ndarray, _check_ndarray, _ndarray_components)
