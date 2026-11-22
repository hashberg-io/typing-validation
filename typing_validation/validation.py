# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The interpreter: walking a value and a type together, once, and answering yes or
no.

This module stands alone, deliberately. It shares no implementation code with
the node model or with any other mechanism, and it never consults their cache —
not even for a hit, because a hit costs a hash of ``t`` and :mod:`typing`
objects do not hash cheaply. The type-form structure is written out explicitly
in the loop below, with no registry, no handler objects and no table dispatch,
because each of those is paid *per node, per value, per call*, and on
``validate(12, int)`` that overhead would be the entire cost of the operation.

What it duplicates is semantics, not code. The catalogue in ``TYPES.md`` is what
binds this module to the other mechanisms, and the conformance suite is what
keeps them honest.
"""

import builtins
import sys
import typing
from collections import defaultdict, deque
from collections.abc import (
    Buffer,
    Callable,
    Collection,
    Container,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Sequence,
    Set,
)
from types import GenericAlias
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    cast,
    get_args,
    get_origin,
    is_protocol,
    is_typeddict,
    Literal,
    NamedTuple,
    Never,
    NewType,
    NoReturn,
    Tuple,
    TypeAliasType,
    TypeVar,
    Union,
)
from annotationlib import ForwardRef

from ._compat import is_bytestring_origin
from .diagnosis import diagnose
from .errors import UnsupportedTypeError, ValidationError
from .plugins import (
    plugin_import,
    registered_validator,
    unsupported_explanation,
)
from ._resolution import resolve, strip_qualifiers

# PEP 747. `type[T]` is what a validation library reaches for and is wrong: it
# rejects `validated(x, int | str)`, `Literal["a", "b"]` and `None` — the most
# ordinary things anyone validates against — because a union, a literal and None
# are type *forms* rather than classes. TypeForm[T] is the form of that
# distinction, and mypy already infers through it.
#
# From 3.15 it is in the standard library. On 3.14 the import is
# type-checking-only, so this stays a zero-dependency library: the name is never
# looked up at runtime, typeshed carries the stub so mypy needs nothing
# installed, and the docs read annotations as strings. The one cost, on 3.14
# only, is that get_type_hints on these functions raises NameError.
if sys.version_info >= (3, 15):
    from typing import TypeForm
elif TYPE_CHECKING:
    from typing_extensions import TypeForm

__all__ = ("is_valid", "validate", "validated", "validated_iter")

_ITEM_ORIGINS = frozenset(
    {
        list,
        set,
        frozenset,
        deque,
        Collection,
        Set,
        MutableSet,
        Sequence,
        MutableSequence,
    }
)
"""Origins whose every item is checked against a single type argument."""

_MAPPING_ORIGINS = frozenset(
    # frozendict is a builtin from 3.15; on 3.14 this falls back to dict, which
    # is already in the set.
    {
        dict,
        defaultdict,
        Mapping,
        MutableMapping,
        getattr(builtins, "frozendict", dict),
    }
)
"""Origins whose every key and value is checked against a type argument each."""

_ITERATOR_ORIGINS = frozenset({Iterator})
"""
Origins that may be one-shot, and whose items therefore cannot be checked at all
without consuming them.
"""

_MAYBE_ITEM_ORIGINS = frozenset({Iterable, Container})
"""
Origins whose items are checked only when the value is also a
:class:`~collections.abc.Collection`, and so can be iterated without being
consumed.

:class:`~collections.abc.Iterable` belongs here and **only** here. v1 listed it
both here and in the iterator table, tested the iterator table first, and thereby
made this arm unreachable — so ``[1, "a"]`` failed ``Collection[int]`` but passed
``Iterable[int]`` for eleven releases. The origin tables are asserted disjoint by
the test suite, which makes that bug unrepresentable rather than merely fixed.
"""

_UNSUPPORTED_ORIGINS: dict[Any, str] = {
    Callable: (
        "Callability is checkable; signatures are not, in general. Checking "
        "only callable(val) while ignoring the signature would be a totality "
        "violation dressed as support."
    ),
}
"""
Origins that are reached but deliberately refused, with the reason.

Without this arm ``Callable[[int], int]`` would fall through to the
generic-class arm and validate on ``isinstance(val, abc.Callable)``, which is
the very half-support the form is refused for.
"""


def validate(val: Any, t: Any, /) -> Literal[True]:
    """
    Validate a value against a type, raising if it does not conform.

    Returns :obj:`True` so that validation can be gated behind an assertion and
    compiled out entirely under ``-O``::

        assert validate(val, t)

    :raises ValidationError: if the value is not valid for the type.
    :raises UnsupportedTypeError: if the type, or any component of it, is not
        one this library can validate against.
    """
    # The scalar fast path, measured rather than assumed. A plain class that is
    # not a named tuple is decided by one isinstance, and going through the work
    # stack to reach that isinstance costs two Python calls, two list
    # allocations and a tuple allocation — 134ns against 46ns, on a hand-written
    # baseline of 31ns. On validate(12, int) the machinery *is* the cost, which
    # is the whole reason this mechanism stands alone. The tuple test is what
    # excludes named tuples, whose fields still need checking.
    if type(t) is type and not issubclass(t, tuple):
        if isinstance(val, t):
            return True
    elif _check(val, t):
        return True
    raise ValidationError(val, t, diagnose(val, t))


def is_valid(val: Any, t: Any, /) -> bool:
    """
    Whether a value is valid for a type.

    This does **not** build an explanation, because a caller who wanted one
    would have called :func:`validate` and caught the exception. Asking for a
    boolean gets you a boolean at boolean prices.

    :raises UnsupportedTypeError: if the type, or any component of it, is not
        one this library can validate against. An unsupported type is not an
        invalid value, and is not reported as :obj:`False`.
    """
    # The same fast path as validate, for the same measured reason.
    if type(t) is type and not issubclass(t, tuple):
        return isinstance(val, t)
    return _check(val, t)


def validated[T](val: Any, t: TypeForm[T], /) -> T:
    """
    Validate a value against a type and return it, for use in an expression.

    :raises ValidationError: if the value is not valid for the type.
    """
    if _check(val, t):
        return cast(T, val)
    raise ValidationError(val, t, diagnose(val, t))


def validated_iter[T](val: Iterable[T], t: Any, /) -> Iterable[T]:
    """
    Validate an iterable's items against a type as they are yielded.

    This is the only honest way to validate an :class:`~typing.Iterator`.
    Determining the items of a one-shot iterator consumes it, so validating them
    eagerly would leave the caller holding an exhausted object — which is why
    ``Iterator[T]`` leaves its item type unchecked. Checking each item on its way
    past costs the caller nothing they were not already paying.

    :raises ValidationError: if the value is not an instance of the type's
        origin, or — when an invalid item is reached, at the point it is
        reached.
    :raises UnsupportedTypeError: if the type is not a parametrised iterable.
    """
    origin = get_origin(t)
    if (
        origin not in _ITEM_ORIGINS
        and origin not in _ITERATOR_ORIGINS
        and origin not in _MAYBE_ITEM_ORIGINS
    ):
        raise UnsupportedTypeError(
            t,
            "validated_iter needs a parametrised iterable type, such as "
            "Iterator[int].",
        )
    if not isinstance(val, origin):
        raise ValidationError(val, t)
    args = get_args(t)
    if not args:
        return cast(Iterable[T], val)
    return _validated_iter(val, args[0])


def _validated_iter[T](val: Iterable[T], item_t: Any, /) -> Iterable[T]:
    for item in val:
        if not _check(item, item_t):
            raise ValidationError(item, item_t, diagnose(item, item_t))
        yield item


def _check(val: Any, t: Any, /) -> bool:
    """
    Whether a value is valid for a type: the interpreter proper.

    The walk is **non-recursive**, via the explicit work stack below. The
    motivation is correctness rather than elegance: what threatens the call stack
    is the nesting depth of the *value*, not of the type. ``list[int]`` is a
    shallow type, and a list nested two thousand deep is a legal value for
    ``list[list[...]]``. A recursive walker would raise :class:`RecursionError`,
    which is neither a validation failure nor an honest error. The flat loop also
    avoids a Python call per node.

    Conjunctive obligations — every item of a ``list[int]``, every key and value
    of a ``dict[K, V]`` — are simply pushed, and the loop drains them. Unions are
    the exception, and are handled by :func:`_backtrack`.

    Failure is hard and cheap: no path is tracked, no failure objects are
    allocated, no context is threaded. This knows *that* it failed, never
    *where*, and hands ``(val, t)`` to ``diagnose`` to find out.
    """
    stack: list[tuple[Any, Any]] = [(val, t)]
    unions: list[list[Any]] = []
    while True:
        # A union member attempt that has drained without failing is a member
        # that validated, which settles the union. Checking here, before
        # anything is popped, is what makes "the attempt finished" observable:
        # the stack is back to the depth it had when the attempt began.
        while unions and len(stack) == unions[-1][2]:
            unions.pop()
        if not stack:
            return True
        val, t = stack.pop()
        tt = type(t)
        if tt is type:
            # Plain classes, bare builtin collections, and NamedTuple
            # subclasses. The overwhelmingly common case, and the only arm that
            # reaches isinstance without a single function call before it.
            if isinstance(val, t):
                # Both halves of this test are load-bearing, and neither alone
                # would do. `_fields` alone is not enough: 133 classes in `ast`
                # carry one, and none is a tuple, so `val[i]` below would raise
                # "object is not subscriptable" on every AST node. `tuple` alone
                # is not enough either: os.stat_result, time.struct_time and
                # sys.version_info are all tuple subclasses with no field names
                # to check. A named tuple is, as far as the runtime is concerned,
                # exactly the conjunction — the only construct that is both
                # positionally addressable and carries field names.
                #
                # If some future class satisfies both without being a named
                # tuple, it will be validated as one. That is the same
                # indistinguishability TYPES.md already records for a
                # hand-written tuple subclass defining `_fields`: there is no
                # nominal marker to check, because typing.NamedTuple is a
                # function and never appears in an __mro__.
                if not issubclass(t, tuple):
                    continue
                fields = getattr(t, "_fields", None)
                if fields is None:
                    continue
                annotations = t.__annotations__
                for i, name in enumerate(fields):
                    ann = annotations.get(name)
                    if ann is None:
                        continue
                    if type(ann) is not type:
                        ann = resolve(ann, t)
                        if isinstance(ann, ForwardRef):
                            raise UnsupportedTypeError(
                                t, _unresolved_explanation(t, name, ann)
                            )
                    stack.append((val[i], ann))
                continue
        else:
            if tt is GenericAlias:
                origin = t.__origin__
                args = t.__args__
            elif tt is Union:  # type: ignore[comparison-overlap]
                origin = Union
                args = t.__args__
            else:
                origin = get_origin(t)
                args = get_args(t)
            if origin is None:
                # Any and None are inlined rather than delegated: they are
                # identity tests on singletons, so they cannot shadow anything,
                # and delegating them would make a Python call the entire cost of
                # validate(val, Any).
                if t is Any:
                    continue
                if t is None:
                    if val is None:
                        continue
                elif _check_bare(val, t, tt, stack):
                    continue
            elif origin is Union:
                # Members that are plain classes collapse to a single isinstance
                # against the argument tuple, which __args__ already is. That
                # covers int | None, str | bytes and int | str | None — the
                # overwhelmingly common shapes — with no flag, no sequence and
                # no attempts. Only structured members need sequential trial.
                simple = True
                for member in args:
                    if type(member) is not type:
                        simple = False
                        break
                if simple:
                    if isinstance(val, args):
                        continue
                else:
                    # A member attempt is the unit of success, and the flag must
                    # be set by the unit completing rather than by any single
                    # obligation inside it: given list[int] | list[str] and
                    # [1, "a"], the 1 validating against int must not settle the
                    # union. The recorded depth is what delimits the attempt.
                    unions.append([val, args, len(stack), 1])
                    stack.append((val, args[0]))
                    continue
            elif origin in _ITEM_ORIGINS:
                if isinstance(val, origin):
                    if not args:
                        continue
                    item_t = args[0]
                    for item in val:
                        stack.append((item, item_t))
                    continue
            elif origin in _MAPPING_ORIGINS:
                if isinstance(val, origin):
                    if not args:
                        continue
                    key_t, value_t = args
                    for key, value in val.items():
                        stack.append((key, key_t))
                        stack.append((value, value_t))
                    continue
            elif origin is tuple:
                if isinstance(val, tuple):
                    if not args:
                        # tuple[()] means the empty tuple, while bare
                        # Tuple means any tuple — and both record no
                        # arguments at all, so only the spelling tells them
                        # apart. Tuple is a singleton, so identity does.
                        if t is Tuple or not val:
                            continue
                    elif len(args) == 2 and args[1] is Ellipsis:
                        item_t = args[0]
                        for item in val:
                            stack.append((item, item_t))
                        continue
                    if len(val) == len(args):
                        for item, item_t in zip(val, args):
                            stack.append((item, item_t))
                        continue
            elif origin is Literal:
                # Matched by type *and* equality, or by identity for enum members
                # and None. v1 tested `val in t.__args__`, which is bare ==, so
                # Literal[1] accepted both True and 1.0. PEP 586 makes a
                # literal's type part of its identity.
                matched = False
                val_t = type(val)
                for literal in args:
                    if literal is val or (
                        type(literal) is val_t and literal == val
                    ):
                        matched = True
                        break
                if matched:
                    continue
            elif origin is Annotated:
                # Not stripped: Annotated[int, Ge(0)] is a distinct type from
                # int, with its own identity, and failures report it as written.
                stack.append((val, t.__origin__))
                continue
            elif origin is type:
                if _check_type_of(val, t, args):
                    continue
            elif origin in _ITERATOR_ORIGINS:
                # The item type is uncheckable without consuming the value, and
                # purity forbids that. validated_iter is the honest route.
                if isinstance(val, Iterator):
                    continue
            elif origin in _MAYBE_ITEM_ORIGINS:
                if isinstance(val, origin):
                    if not args or not isinstance(val, Collection):
                        # Not a Collection, so potentially one-shot: same rule as
                        # Iterator[T], for the same reason.
                        continue
                    item_t = args[0]
                    for item in val:
                        stack.append((item, item_t))
                    continue
            # ByteString is deprecated, but remains a supported input form;
            # check it as Buffer without touching the deprecated origin class.
            elif is_bytestring_origin(origin):
                if isinstance(val, Buffer):
                    continue
            elif origin in _UNSUPPORTED_ORIGINS:
                raise UnsupportedTypeError(t, _UNSUPPORTED_ORIGINS[origin])
            elif type(origin) is TypeAliasType:
                # A generic alias: type Pair[T] = tuple[T, T]. Subscripting the
                # alias's value substitutes the arguments for its parameters.
                stack.append((val, origin.__value__[args]))
                continue
            elif isinstance(origin, type):
                if _check_generic_class(val, t, origin, args, stack):
                    continue
            else:
                raise UnsupportedTypeError(t)
        if _backtrack(stack, unions):
            continue
        return False


def _check_bare(
    val: Any, t: Any, tt: type, stack: list[tuple[Any, Any]], /
) -> bool:
    """
    The arm for types with no origin, other than :obj:`~typing.Any` and
    :obj:`None`: everything that is neither parametrised nor a plain class.

    Returns whether the check succeeded, having pushed any further obligations.
    """
    if tt is TypeAliasType:
        # Not transparent: type MyInt = int keeps its own identity and reports as
        # itself. It is also where a recursive type closes its cycle.
        stack.append((val, t.__value__))
        return True
    if tt is TypeVar:
        bound = t.__bound__
        if bound is not None:
            stack.append((val, bound))
            return True
        constraints = t.__constraints__
        if constraints:
            # A constrained type variable is semantically the union of its
            # constraints. v1 ignored them, so validate(1.5, T) passed for a T
            # constrained to int and str.
            stack.append((val, Union[constraints]))
            return True
        return True
    if tt is NewType:
        # Vacuous beyond the supertype: NewType's constructor is the identity
        # function and isinstance against it raises, so there is no runtime
        # witness of the distinction. The type is not stripped, so failures
        # report UserId rather than int.
        stack.append((val, t.__supertype__))
        return True
    if t is NamedTuple:
        # "Any named tuple instance", which is what type checkers enforce. There
        # is no nominal marker to check — NamedTuple is a function, and
        # never appears in a named tuple's __mro__ — so the structural probe is
        # the only runtime witness there is.
        return isinstance(val, tuple) and hasattr(type(val), "_fields")
    if isinstance(t, type):
        if is_typeddict(t) or _is_extensions_typed_dict(t):
            return _check_typed_dict(val, t, stack)
        if is_protocol(t):
            if not getattr(t, "_is_runtime_protocol", False):
                raise UnsupportedTypeError(
                    t,
                    "Protocol is not runtime-checkable: isinstance against it "
                    "raises. Decorate it with @typing.runtime_checkable.",
                )
        return isinstance(val, t)
    if isinstance(t, (str, ForwardRef)):
        raise UnsupportedTypeError(t, _INLINE_FORWARD_REF_EXPLANATION)
    raise UnsupportedTypeError(t)


def _is_extensions_typed_dict(t: type, /) -> bool:
    """
    Whether a class is a ``TypedDict`` defined with ``typing_extensions``, which
    :func:`typing.is_typeddict` does not recognise.

    Such a class can only exist if ``typing_extensions`` has been imported, so
    asking it costs no import of our own.
    """
    extensions = sys.modules.get("typing_extensions")
    return extensions is not None and bool(extensions.is_typeddict(t))


_OPEN = object()
"""The extra-items setting of a ``TypedDict`` that leaves them unconstrained."""

_CLOSED = object()
"""The extra-items setting of a ``TypedDict`` that allows none."""

_ABSENT = object()
"""What a class without ``__extra_items__`` is read as having."""


def _typed_dict_extras(t: Any, /) -> Any:
    """
    What a ``TypedDict`` requires of keys it does not declare (PEP 728):
    :data:`_OPEN`, :data:`_CLOSED`, or the type their values must have.

    The class records only the arguments it was itself given, so a setting it
    leaves unspecified is inherited from the ``TypedDict`` classes it derives
    from. Its own arguments win otherwise, even where a type checker would reject
    the definition: policing that is the checker's job, not the validator's.

    :raises UnsupportedTypeError: if it inherits conflicting settings.
    """
    closed = getattr(t, "__closed__", None)
    if closed is True:
        return _CLOSED
    extra = getattr(t, "__extra_items__", _ABSENT)
    if not _declares_no_extra_items(extra):
        ann = strip_qualifiers(resolve(extra, t))
        if ann is Never or ann is NoReturn:
            return _CLOSED
        return ann
    if closed is False:
        return _OPEN
    found = _OPEN
    for base in getattr(t, "__orig_bases__", ()):
        # Most bases are TypedDict itself, which is a function: ruling it out
        # with an attribute lookup rather than get_origin keeps this cheap, and
        # this runs on every call.
        cls = (
            base
            if isinstance(base, type)
            else getattr(base, "__origin__", None)
        )
        if not isinstance(cls, type):
            continue
        if not (is_typeddict(cls) or _is_extensions_typed_dict(cls)):
            continue
        setting = _typed_dict_extras(cls)
        if setting is _OPEN or setting is found:
            continue
        if found is _OPEN:
            found = setting
        elif setting != found:
            raise UnsupportedTypeError(t, _CONFLICTING_EXTRAS_EXPLANATION)
    return found


_NO_EXTRA_ITEMS = getattr(typing, "NoExtraItems", _ABSENT)
"""The standard library's marker for *no extra items given*, from 3.15."""

_PLAIN_BASES = (typing.TypedDict,)
"""The ``__orig_bases__`` of a ``TypedDict`` that derives from no other."""


def _declares_no_extra_items(extra: Any, /) -> bool:
    """
    Whether an ``__extra_items__`` value is the marker for *not given*:
    :obj:`typing.NoExtraItems` from 3.15, its own object in
    ``typing_extensions`` on 3.14.
    """
    if extra is _NO_EXTRA_ITEMS or extra is _ABSENT:
        return True
    extensions = sys.modules.get("typing_extensions")
    return extensions is not None and extra is getattr(
        extensions, "NoExtraItems", _ABSENT
    )


def _check_typed_dict(
    val: Any, t: Any, stack: list[tuple[Any, Any]], /
) -> bool:
    """
    The arm for :class:`~typing.TypedDict`.

    Keys it does not declare are checked as PEP 728 says: ignored, refused, or
    held to the extra-items type. It is not checked that the value is *actually*
    a ``TypedDict`` instance, which has no runtime identity — any conforming
    mapping is indistinguishable from one.
    """
    # The overwhelmingly common TypedDict gives no setting and derives from no
    # other, and this recognises it without a call: the check runs per value.
    if (
        getattr(t, "__closed__", None) is None
        and getattr(t, "__extra_items__", _NO_EXTRA_ITEMS) is _NO_EXTRA_ITEMS
        and getattr(t, "__orig_bases__", _PLAIN_BASES) == _PLAIN_BASES
    ):
        extras = _OPEN
    else:
        extras = _typed_dict_extras(t)
    if not isinstance(val, Mapping):
        return False
    for key in t.__required_keys__:
        if key not in val:
            return False
    # Requiredness comes from __required_keys__ rather than being re-derived from
    # the qualifiers: the class computes it, and it stays correct under
    # inheritance and total=False.
    annotations = t.__annotations__
    for key, item in val.items():
        if not isinstance(key, str):
            return False
        ann = annotations.get(key)
        if ann is None:
            if extras is _OPEN:
                continue
            if extras is _CLOSED:
                return False
            if isinstance(extras, ForwardRef):
                raise UnsupportedTypeError(
                    t, _unresolved_extras_explanation(t, extras)
                )
            stack.append((item, extras))
            continue
        if type(ann) is not type:
            ann = strip_qualifiers(resolve(ann, t))
            if isinstance(ann, ForwardRef):
                raise UnsupportedTypeError(
                    t, _unresolved_explanation(t, key, ann)
                )
        stack.append((item, ann))
    return True


def _check_type_of(val: Any, t: Any, args: tuple[Any, ...], /) -> bool:
    """
    The arm for ``Type[T]`` and ``type[T]``.

    ``T`` may be a class, a union of classes, or :obj:`~typing.Any`. Anything
    else — ``Type[list[int]]`` and friends — is unsupported: :func:`issubclass`
    cannot express it, and inventing a bespoke subtype relation is out of scope.

    The argument is judged before the value, and the order is the whole point.
    Laziness (``TYPES.md``, *When the error surfaces*) lets a value be rejected
    before an unsupported component is reached — but that component must be one
    the walk had yet to *reach*. Here it is this node: an unparametrisable ``T``
    makes the whole ``Type[T]`` unsupported, with no supported outer layer whose
    obligation ``isinstance(val, type)`` could be discharging. Testing the value
    first made the verdict on the *type* depend on the value, so
    ``Type[list[int]]`` was unsupported against one value and merely invalid
    against another — and diagnosis, which reads the type alone, could not
    reproduce the second and reported itself as a bug.
    """
    target = _type_of_target(t, args)
    if not isinstance(val, type):
        return False
    if target is None:
        return True
    return issubclass(val, target)


def _type_of_target(
    t: Any, args: tuple[Any, ...], /
) -> type | tuple[type, ...] | None:
    """
    What ``Type[T]`` requires the value to be a subclass of, or :obj:`None` when
    it requires nothing beyond being a class.

    :raises UnsupportedTypeError: if ``T`` is anything :func:`issubclass` cannot
        take.
    """
    if not args:
        return None
    (arg,) = args
    if arg is Any:
        return None
    union = type(arg) is Union  # type: ignore[comparison-overlap]
    members = arg.__args__ if union else (arg,)
    for member in members:
        if type(member) is type:
            continue
        if not isinstance(member, type):
            raise UnsupportedTypeError(t, _TYPE_ARG_EXPLANATION)
        try:
            issubclass(object, member)
        except TypeError:
            raise UnsupportedTypeError(
                t, _TYPE_ARG_REFUSED_EXPLANATION
            ) from None
    target: type | tuple[type, ...] = members if union else arg
    return target


def _check_generic_class(
    val: Any,
    t: Any,
    origin: type,
    args: tuple[Any, ...],
    stack: list[tuple[Any, Any]],
    /,
) -> bool:
    """
    The arm for a parametrised class the core knows nothing about — and, by that
    very fact, the extension point.

    A class that declares a ``__validate__`` classmethod, or that has a
    registered validator, says how its arguments are checked. Absent either, the
    arguments go unchecked and the class validates on its origin alone: a generic
    class does not, in general, expose enough at runtime to determine them, so
    that is the specified meaning rather than a shortfall. It is *not* an error
    to parametrise a class we cannot introspect.

    The exception is a class this distribution ships a plugin for, whose
    arguments *are* determinable. Leaving those unchecked would report success we
    had not earned, so it is an error naming the import that would fix it.
    """
    check = getattr(origin, "__validate__", None)
    if check is None:
        check = registered_validator(origin)
    if check is None:
        if plugin_import(origin) is not None:
            raise UnsupportedTypeError(t, unsupported_explanation(origin))
        return isinstance(val, origin)
    if not isinstance(val, origin):
        return False
    return bool(check(val, args))


def _backtrack(
    stack: list[tuple[Any, Any]], unions: list[list[Any]], /
) -> bool:
    """
    Move to the next member of the innermost union attempt, if there is one.

    Returns whether validation may continue. :obj:`False` means the failure was
    not inside any union attempt, or that every enclosing union has run out of
    members, so it is final.

    This is reached only on failure, which is exceptional by definition, so the
    loop above pays nothing for its existence. Discarding the failed attempt's
    leftovers is sound only because validation is pure: a member that failed
    part-way leaves nothing behind for the next member to trip over.
    """
    while unions:
        val, members, depth, index = unions[-1]
        if index < len(members):
            del stack[depth:]
            unions[-1][3] = index + 1
            stack.append((val, members[index]))
            return True
        # This union has no members left, so it has failed — which is itself a
        # failure of whatever attempt encloses it. Keep unwinding.
        unions.pop()
    return False


_INLINE_FORWARD_REF_EXPLANATION = (
    "A forward reference written inline records no module and no owner, so "
    "there is nothing to resolve it against. Note that resolving it against "
    "the calling frame is not an option: validators are interned, so the same "
    "reference would mean whatever the first caller to build it meant.\n"
    "Use a PEP 695 type alias instead: 'type JSON = int | list[JSON]', which "
    "is lazily evaluated and resolves against the module that defines it."
)


_TYPE_ARG_EXPLANATION = (
    "Type[T] supports T being a class, a union of classes, or Any. issubclass "
    "cannot express anything else, and this library does not invent a subtype "
    "relation of its own."
)

_TYPE_ARG_REFUSED_EXPLANATION = (
    "Type[T] is checked with issubclass, which refuses this T: TypedDicts, "
    "protocols that are not runtime-checkable, and protocols with non-method "
    "members all raise when used as its second argument."
)


def _unresolved_extras_explanation(t: Any, ref: ForwardRef, /) -> str:
    """The explanation for an extra-items type naming something nonexistent."""
    return (
        f"The extra items of {t.__qualname__!r} refer to unresolved name "
        f"{ref.__forward_arg__!r}."
    )


_CONFLICTING_EXTRAS_EXPLANATION = (
    "TypedDict inherits conflicting extra-items settings from its bases, "
    "and does not settle them with closed= or extra_items= of its own."
)


def _unresolved_explanation(t: Any, field: str, ref: ForwardRef, /) -> str:
    """The explanation for an annotation naming something that does not exist."""
    return (
        f"Field {field!r} of {t.__qualname__!r} refers to unresolved name "
        f"{ref.__forward_arg__!r}."
    )
