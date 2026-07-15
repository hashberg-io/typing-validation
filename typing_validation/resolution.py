# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Reading the component types that some forms record in annotations rather than
in ``__args__``: :class:`~typing.TypedDict` fields and
:class:`~typing.NamedTuple` fields.

Under PEP 649 an annotation is evaluated lazily, and a name that was not yet
defined survives as a :class:`~annotationlib.ForwardRef` rather than resolving.
Resolving those is this module's job.

:func:`~typing.get_type_hints` does it too, and is rejected for one decisive
reason: it is all-or-nothing. A single unresolvable field raises
:class:`NameError` for the whole class, and that error escapes from inside
:func:`~typing_validation.validate` as neither a validation failure nor an
:class:`~typing_validation.UnsupportedTypeError` — just a stray exception from a
library the caller did not know was evaluating anything. Resolving field by
field turns that opaque crash into a precise report, and lets the unresolvable
field poison only the type that contains it.
"""

import typing
from collections.abc import Mapping
from types import GenericAlias
from typing import Annotated, Any, Union

from annotationlib import ForwardRef, Format, get_annotations

__all__ = (
    "field_annotations",
    "resolve",
    "resolved_field_annotations",
    "strip_qualifiers",
)

_QUALIFIERS = frozenset({typing.Required, typing.NotRequired, typing.ReadOnly})
"""
The :class:`~typing.TypedDict` qualifiers, none of which bears on the shape of a
value.

``Required`` and ``NotRequired`` are redundant with ``__required_keys__`` and
``__optional_keys__``, which the class computes and which stay correct under
inheritance and ``total=False``. ``ReadOnly`` constrains assignment rather than
value shape, and has no runtime meaning at all.

:func:`~typing.get_type_hints` strips these for us; :mod:`annotationlib` does
not, so the obligation is inherited along with the better resolution path.
"""


def strip_qualifiers(ann: Any, /) -> Any:
    """
    Remove any :class:`~typing.Required`, :class:`~typing.NotRequired` and
    :class:`~typing.ReadOnly` wrappers from an annotation.

    They nest — ``NotRequired[ReadOnly[float]]`` is legal — so this loops.
    """
    while typing.get_origin(ann) in _QUALIFIERS:
        (ann,) = typing.get_args(ann)
    return ann


def resolve(ann: Any, owner: Any, /) -> Any:
    """
    Resolve every forward reference in an annotation, against the module that
    defines ``owner``.

    References that resolve are replaced by what they name; references that do
    not are left in place as :class:`~annotationlib.ForwardRef` objects, for the
    caller to report against. No :class:`NameError` escapes.

    ``owner`` is not optional, and is not a convenience. A reference nested
    inside an annotation — the ``'Later'`` in ``list["Later"]`` — records no
    module of its own, and neither does *any* reference in a
    :class:`~typing.NamedTuple` field, even a top-level one. Only a top-level
    :class:`~typing.TypedDict` annotation happens to record one. So the module
    is recovered from the owning class in every case, which is both uniform and
    the only thing that works.

    This is what separates a resolvable reference from an unresolvable one: not
    whether the reference carries a module, but whether we know the class whose
    annotation it came from. An inline ``validate(x, list["JSON"])`` has no
    owner, and that — rather than the shape of the reference — is why it cannot
    be resolved.

    :param ann: the annotation to resolve.
    :param owner: the class whose annotation this is.
    """
    if isinstance(ann, str):
        ann = ForwardRef(ann, owner=owner)
    if isinstance(ann, ForwardRef):
        resolved = ann.evaluate(owner=owner, format=Format.FORWARDREF)
        if isinstance(resolved, ForwardRef):
            return resolved
        return resolve(resolved, owner)
    origin = typing.get_origin(ann)
    if origin is typing.Literal:
        # A literal's arguments are values, not types. Resolving them would read
        # the 'a' of Literal['a'] as a forward reference to a class named a.
        return ann
    if origin is Annotated:
        base = resolve(ann.__origin__, owner)
        if base is ann.__origin__:
            return ann
        return Annotated[(base, *ann.__metadata__)]
    args = typing.get_args(ann)
    if not args:
        return ann
    new_args = tuple(
        arg if arg is Ellipsis else resolve(arg, owner) for arg in args
    )
    if new_args == args:
        return ann
    if origin is Union:
        return Union[new_args]
    if isinstance(ann, GenericAlias):
        return origin[new_args]
    copy_with = getattr(ann, "copy_with", None)
    if copy_with is None:
        return ann
    return copy_with(new_args)


def field_annotations(t: Any, /) -> Mapping[str, Any]:
    """
    The annotations of a :class:`~typing.TypedDict` or
    :class:`~typing.NamedTuple` class, exactly as recorded: qualifiers intact,
    forward references unresolved, inherited fields included.

    :param t: the class whose fields to read.
    """
    return get_annotations(t, format=Format.FORWARDREF)


def resolved_field_annotations(t: Any, /) -> Mapping[str, Any]:
    """
    The annotations of a :class:`~typing.TypedDict` or
    :class:`~typing.NamedTuple` class, with forward references resolved and
    qualifiers stripped.

    A field whose reference could not be resolved keeps its
    :class:`~annotationlib.ForwardRef`, which is what the caller reports as
    unsupported.

    Resolution happens before stripping, because a qualifier may itself have
    been written as a reference — ``"Required[int]"`` resolves to
    ``Required[int]`` and only then has a qualifier to strip.

    :param t: the class whose fields to read.
    """
    return {
        name: strip_qualifiers(resolve(ann, t))
        for name, ann in field_annotations(t).items()
    }
