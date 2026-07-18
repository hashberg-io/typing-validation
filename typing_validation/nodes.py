# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The node model: one interned node per distinct type, holding the type it was
built from, its form, its interned children, and its memoised properties.

Everything except :func:`~typing_validation.validation.validate` is built on this one
class. It is simultaneously the unit of interning, the thing
:func:`~typing_validation.inspection.inspect_type` reports, and the thing that explains a
failure. It can be all of those at once precisely because none of them is on a
hot path — which is also why this module may share freely with them, and why it
shares nothing with the interpreter.
"""

# The reusable validators hang off this class too, when they land: the closure
# compositor and the source emitter are further methods on the node, for the same
# reason the rest are. See DESIGN.md §3.3 and §3.4.

import enum
from collections import defaultdict, deque
from collections.abc import (
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
    Annotated,
    Any,
    ByteString,
    final,
    get_args,
    get_origin,
    is_protocol,
    is_typeddict,
    Literal,
    NamedTuple,
    NewType,
    Self,
    Tuple,
    TypeAliasType,
    TypeVar,
    Union,
)

from annotationlib import ForwardRef

from . import _cache as cache
from ._display import safe_repr
from .plugins import (
    plugin_import,
    registered_components,
    registered_validator,
    unsupported_explanation,
)
from ._resolution import resolve, strip_qualifiers

__all__ = ("TypeForm", "TypeNode", "node_for")


@final
class TypeForm(enum.Enum):
    """
    What kind of type a node is, mirroring the catalogue in ``TYPES.md``.
    """

    ANY = "Any"
    """:obj:`~typing.Any`: every value is valid."""

    NONE = "None"
    """:obj:`None` and :class:`types.NoneType`."""

    CLASS = "class"
    """A plain class or abstract base class, checked with :func:`isinstance`."""

    COLLECTION = "collection"
    """A collection whose every item is checked against one type argument."""

    MAPPING = "mapping"
    """A mapping whose keys and values are each checked against an argument."""

    TUPLE = "tuple"
    """A fixed-length, variadic or empty tuple."""

    UNION = "union"
    """A union: valid if at least one member is."""

    LITERAL = "literal"
    """A :obj:`~typing.Literal`, whose children are values rather than types."""

    TYPE_VAR = "type variable"
    """A type variable, checked against its bound or its constraints."""

    TYPED_DICT = "TypedDict"
    """A :class:`~typing.TypedDict`, whose children are its field types."""

    NAMED_TUPLE = "NamedTuple"
    """A concrete named tuple class, whose children are its field types."""

    ANY_NAMED_TUPLE = "any NamedTuple"
    """Bare :class:`typing.NamedTuple`: any named tuple instance."""

    TYPE_OF = "type of"
    """``Type[T]`` and ``type[T]``."""

    PROTOCOL = "protocol"
    """A runtime-checkable protocol."""

    GENERIC_CLASS = "generic class"
    """A parametrised class whose arguments cannot be checked, by design."""

    PLUGIN = "plugin"
    """A parametrised class whose arguments a plugin knows how to check."""

    ALIAS = "alias"
    """A PEP 695 type alias, and the point at which a recursive type closes."""

    ANNOTATED = "Annotated"
    """:obj:`~typing.Annotated`, validated as the type it wraps."""

    NEW_TYPE = "NewType"
    """A :class:`~typing.NewType`, validated as its supertype."""

    ITERATOR = "iterator"
    """An iterator, whose items cannot be checked without consuming it."""

    MAYBE_ITEMS = "iterable or container"
    """
    An iterable or container, whose items are checked only when the value is
    also a :class:`~collections.abc.Collection`.
    """

    UNSUPPORTED = "unsupported"
    """A type we cannot validate against. Poisons whatever contains it."""


_COLLECTION_ORIGINS = frozenset(
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
_MAPPING_ORIGINS = frozenset({dict, defaultdict, Mapping, MutableMapping})
_ITERATOR_ORIGINS = frozenset({Iterator})
_MAYBE_ITEM_ORIGINS = frozenset({Iterable, Container})
_BYTESTRING_ORIGIN = get_origin(ByteString)


@final
class TypeNode:
    """
    One distinct type, analysed.

    Nodes are interned on the type itself, so ``list[int]`` is analysed once and
    shared everywhere it occurs. **Interning is never semantically observable**:
    a cold, cleared or bypassed cache changes cost and nothing else. That is what
    lets an unhashable type simply skip the cache, and what makes eviction safe
    to expose at all.
    """

    __slots__ = (
        "_t",
        "_form",
        "_children",
        "_labels",
        "_supported",
        "_reason",
        "_check",
        "_can_push",
    )

    _t: Any
    """The type this node was built from. Display is its :func:`repr`."""

    _form: TypeForm
    """What kind of type this is."""

    _children: tuple[TypeNode, ...]
    """The interned nodes for this type's component types."""

    _labels: tuple[str, ...] | None
    """
    Names for the children, where they have them: field names for a
    :class:`~typing.TypedDict` or named tuple. :obj:`None` otherwise.
    """

    _supported: bool
    """
    Whether this type, and every component of it, can be validated against.

    Memoised per node, which is what makes ``can_validate`` a lookup rather than
    a walk.
    """

    _reason: str | None
    """Why this node itself is unsupported, if it is. :obj:`None` otherwise."""

    _check: Any
    """
    The composed check for this type, once something has asked for one.

    Memoised here rather than beside the compositor because a cycle needs a slot
    to close through: a check that is still being built cannot be captured, so
    the back-edge reads this at call time instead.
    """

    _can_push: bool
    """Whether :attr:`_check` can descend, which is what decides call-versus-push."""

    def __new__(cls, t: Any, /) -> Self:
        self = object.__new__(cls)
        self._t = t
        self._form = TypeForm.UNSUPPORTED
        self._children = ()
        self._labels = None
        # Optimistic, and provisional: a node is published before its children
        # exist, so that a back-edge finds it and construction terminates. A
        # cycle alone must not make a type unsupported, so True is the neutral
        # value to start from. _settle_support then iterates to a fixed point.
        self._supported = True
        self._reason = None
        self._check = None
        self._can_push = False
        return self

    @property
    def t(self) -> Any:
        """The type this node describes."""
        return self._t

    @property
    def form(self) -> TypeForm:
        """What kind of type this is."""
        return self._form

    @property
    def children(self) -> tuple[TypeNode, ...]:
        """The nodes for this type's component types."""
        return self._children

    @property
    def labels(self) -> tuple[str, ...] | None:
        """Names for the children, where they have them."""
        return self._labels

    @property
    def supported(self) -> bool:
        """
        Whether this type, and every component of it, can be validated against.

        Support is all-or-nothing: one unsupported component poisons the whole
        type, transitively.
        """
        return self._supported

    @property
    def reason(self) -> str | None:
        """Why this node itself is unsupported, if it is."""
        return self._reason

    def unsupported_components(self) -> tuple[TypeNode, ...]:
        """
        The nodes that make this type unsupported, in the order met.

        Totality means the answer to *"can this be validated"* is always "no"
        once anything in here is non-empty. It should never be an opaque "no",
        so this names the culprits rather than the victim.
        """
        found: list[TypeNode] = []
        seen: set[int] = set()
        stack = [self]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            if node._form is TypeForm.UNSUPPORTED:
                found.append(node)
                continue
            stack.extend(reversed(node._children))
        return tuple(found)

    def walk(self) -> Iterator[TypeNode]:
        """
        Every distinct node reachable from this one, including itself.

        Terminates on recursive types: the graph is not a tree, and not even a
        DAG, so nodes already met are not revisited.
        """
        seen: set[int] = set()
        stack = [self]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            yield node
            stack.extend(reversed(node._children))

    def __repr__(self) -> str:
        mark = "" if self._supported else ", unsupported"
        return f"<TypeNode {safe_repr(self._t)}: {self._form.value}{mark}>"


def node_for(t: Any, /) -> TypeNode:
    """
    The interned node for a type, building it if it is not already cached.
    """
    fresh: list[TypeNode] = []
    root, is_new = _intern(t, fresh)
    if not is_new:
        return root
    # Iterative, for the same reason the interpreter is: a type can be deep. It
    # is tempting to think depth only arrives via recursive aliases, which
    # terminate at a name — but `list[list[...[int]]]` nested three thousand
    # deep is an ordinary type with no recursion in it at all, and a recursive
    # builder raises RecursionError on it while `validate` handles the matching
    # value without blinking. Two mechanisms disagreeing about the same type,
    # one of them by crashing, is exactly what the work stack exists to prevent.
    pending = [root]
    while pending:
        node = pending.pop()
        form, child_types, labels, reason = _classify(node._t)
        node._form = form
        node._labels = labels
        node._reason = reason
        if form is TypeForm.UNSUPPORTED:
            node._supported = False
        children: list[TypeNode] = []
        for child_t in child_types:
            child, child_is_new = _intern(child_t, fresh)
            children.append(child)
            if child_is_new:
                pending.append(child)
        node._children = tuple(children)
    _settle_support(fresh)
    return root


def _intern(t: Any, fresh: list[TypeNode], /) -> tuple[TypeNode, bool]:
    """
    The node for a type, and whether it was created here and so needs analysing.

    **Hash-cons before descending**: the node is published *before* its children
    exist, so a back-edge finds the in-progress node and construction
    terminates. A cycle can only close through a name — a PEP 695 alias or a
    forward reference — and names are always hashable, so a cycle root is always
    in the cache, even when unhashable leaves sit inside the cycle.
    """
    try:
        cached = cache.lookup(t)
    except TypeError:
        # Unhashable, and so unshareable: Annotated[int, {"ge": 0}] is exactly
        # the pydantic-style idiom the Annotated decision exists to accommodate,
        # so this is not a corner case. It builds a fresh node, forgoes sharing,
        # and remains fully supported. Interning is an optimisation; skipping it
        # may cost, and may not change an answer.
        node = TypeNode(t)
        fresh.append(node)
        return node, True
    if cached is not None:
        return cached, False
    node = TypeNode(t)
    cache.store(t, node)
    fresh.append(node)
    return node, True


def _settle_support(fresh: list[TypeNode], /) -> None:
    """
    Propagate unsupportedness to a fixed point across the newly built nodes.

    A single pass will not do it, and the reason is a real trap. Nodes start
    optimistically supported so that back-edges have a neutral value to read, so
    given ``type Bad = list[Bad] | Callable[[int], int]`` the node for
    ``list[Bad]`` reads ``Bad`` as supported and settles on True — and then
    ``Bad`` itself turns out to be unsupported, because of the ``Callable``,
    leaving ``list[Bad]`` stale and wrong. Iterating until nothing changes fixes
    it.

    This terminates because support only ever moves from True to False, and only
    finitely many nodes are involved. Only *fresh* nodes take part: a cached node
    already holds its final answer, and nothing cached can point at a node
    younger than itself.
    """
    changed = True
    while changed:
        changed = False
        for node in fresh:
            if not node._supported:
                continue
            if node._form is TypeForm.UNSUPPORTED or not all(
                child._supported for child in node._children
            ):
                node._supported = False
                changed = True


Classified = tuple[
    TypeForm, tuple[Any, ...], tuple[str, ...] | None, str | None
]
"""
What a type turns out to be: its form, the types of its children, names for
those children where they have them, and why it is unsupported when it is.

The children are *types*, not nodes. Classification is deliberately pure — it
builds nothing and interns nothing — because that is what lets :func:`node_for`
drive it from a work stack instead of recursing.
"""


def _plain(form: TypeForm, /) -> Classified:
    return form, (), None, None


def _with(form: TypeForm, *children: Any) -> Classified:
    return form, children, None, None


def _unsupported(reason: str | None = None, /) -> Classified:
    return TypeForm.UNSUPPORTED, (), None, reason


def _classify(t: Any, /) -> Classified:
    """
    What a type is, and what it is made of.

    This duplicates the interpreter's dispatch, deliberately and by design: the
    two share a specification rather than an implementation. Here the shape is
    chosen for clarity, because nothing on this path is hot; there it is chosen
    for speed. The conformance suite is what keeps them agreeing.
    """
    tt = type(t)
    if t is Any:
        return _plain(TypeForm.ANY)
    if t is None or t is type(None):
        return _plain(TypeForm.NONE)
    if t is NamedTuple:
        return _plain(TypeForm.ANY_NAMED_TUPLE)
    if tt is TypeAliasType:
        return _with(TypeForm.ALIAS, t.__value__)
    if tt is TypeVar:
        if t.__bound__ is not None:
            return _with(TypeForm.TYPE_VAR, t.__bound__)
        if t.__constraints__:
            return _with(TypeForm.TYPE_VAR, Union[t.__constraints__])
        return _plain(TypeForm.TYPE_VAR)
    if tt is NewType:
        return _with(TypeForm.NEW_TYPE, t.__supertype__)
    if isinstance(t, (str, ForwardRef)):
        return _unsupported(_INLINE_FORWARD_REF_REASON)
    if tt is type or isinstance(t, type):
        return _classify_class(t)
    if tt is GenericAlias:
        origin = t.__origin__
        args: tuple[Any, ...] = t.__args__
    elif tt is Union:  # type: ignore[comparison-overlap]
        origin = Union
        args = t.__args__
    else:
        origin = get_origin(t)
        args = get_args(t)
    if origin is None:
        return _unsupported()
    if origin is Union:
        return TypeForm.UNION, args, None, None
    if origin is Literal:
        # The children of a Literal are values, not types, so it has none.
        return _plain(TypeForm.LITERAL)
    if origin is Annotated:
        # Not stripped: Annotated[int, Ge(0)] is a distinct type from int, keeps
        # its own identity and its own cache entry, and reports as written.
        return _with(TypeForm.ANNOTATED, t.__origin__)
    if origin in _COLLECTION_ORIGINS:
        return TypeForm.COLLECTION, args[:1], None, None
    if origin in _MAPPING_ORIGINS:
        labels = ("key", "value") if args[:2] else None
        return TypeForm.MAPPING, args[:2], labels, None
    if origin is tuple:
        return _classify_tuple(t, args)
    if origin is type:
        return _classify_type_of(args)
    if origin in _ITERATOR_ORIGINS:
        return _plain(TypeForm.ITERATOR)
    if origin in _MAYBE_ITEM_ORIGINS:
        return TypeForm.MAYBE_ITEMS, args[:1], None, None
    if origin is _BYTESTRING_ORIGIN:
        return _plain(TypeForm.CLASS)
    if origin is Callable:
        return _unsupported(_CALLABLE_REASON)
    if type(origin) is TypeAliasType:
        return _with(TypeForm.ALIAS, origin.__value__[args])
    if isinstance(origin, type):
        return _classify_parametrised_class(origin, args)
    return _unsupported()


def _classify_class(t: Any, /) -> Classified:
    if is_typeddict(t):
        fields = _typed_dict_fields(t)
        names = tuple(name for name, _ in fields)
        return TypeForm.TYPED_DICT, tuple(a for _, a in fields), names, None
    if is_protocol(t):
        if not getattr(t, "_is_runtime_protocol", False):
            return _unsupported(_NON_RUNTIME_PROTOCOL_REASON)
        return _plain(TypeForm.PROTOCOL)
    if issubclass(t, tuple) and getattr(t, "_fields", None) is not None:
        annotations = getattr(t, "__annotations__", {})
        pairs = [
            (name, resolve(annotations[name], t))
            for name in t._fields
            if name in annotations
        ]
        names = tuple(name for name, _ in pairs)
        return TypeForm.NAMED_TUPLE, tuple(a for _, a in pairs), names, None
    return _plain(TypeForm.CLASS)


def _classify_tuple(t: Any, args: tuple[Any, ...], /) -> Classified:
    if not args:
        # Bare typing.Tuple means any tuple; tuple[()] means the empty tuple.
        # Both record no arguments, so only the spelling tells them apart.
        return _plain(TypeForm.CLASS if t is Tuple else TypeForm.TUPLE)
    if len(args) == 2 and args[1] is Ellipsis:
        return TypeForm.TUPLE, args[:1], None, None
    return TypeForm.TUPLE, args, None, None


def _classify_type_of(args: tuple[Any, ...], /) -> Classified:
    if not args:
        return _plain(TypeForm.TYPE_OF)
    (arg,) = args
    if arg is Any or type(arg) is type:
        return _with(TypeForm.TYPE_OF, arg)
    if type(arg) is Union:  # type: ignore[comparison-overlap]
        for member in arg.__args__:
            if type(member) is not type:
                return _unsupported(_TYPE_ARG_REASON)
        return _with(TypeForm.TYPE_OF, arg)
    return _unsupported(_TYPE_ARG_REASON)


def _classify_parametrised_class(
    origin: type, args: tuple[Any, ...], /
) -> Classified:
    """
    The arm for a parametrised class the core knows nothing about — and, by that
    very fact, the extension point.

    A class that declares a ``__validate__`` classmethod, or that has a
    registered validator, says how its arguments are checked. Absent either, the
    arguments go unchecked and the class validates on its origin alone: a generic
    class does not, in general, expose enough at runtime to determine them, so
    that is the specified meaning rather than a shortfall. It is *not* an error
    to parametrise a class we cannot introspect — so its arguments are not
    children either, a child being a component that bears on the verdict.

    The exception is a class this distribution ships a plugin for, whose
    arguments *are* determinable. Leaving those unchecked would report success we
    had not earned, so it is an error naming the import that would fix it.
    """
    check = getattr(origin, "__validate__", None)
    if check is None:
        check = registered_validator(origin)
    if check is None:
        if plugin_import(origin) is not None:
            return _unsupported(unsupported_explanation(origin))
        return _plain(TypeForm.GENERIC_CLASS)
    # Only the arguments the plugin *declares* as components are children, and
    # only they propagate totality. The core cannot tell which of a plugin's
    # arguments it validates and which are specifications the plugin interprets:
    # numpy.ndarray[shape, dtype] has one of each, and treating the dtype as a
    # component would poison every array type, since numpy.dtype[numpy.uint8] is
    # itself a parametrised numpy class with no validator of its own.
    positions = registered_components(origin)
    if positions is None:
        return _plain(TypeForm.PLUGIN)
    children = tuple(args[i] for i in positions if i < len(args))
    return TypeForm.PLUGIN, children, None, None


def _typed_dict_fields(t: Any, /) -> list[tuple[str, Any]]:
    """
    A ``TypedDict``'s field names and resolved types.

    Requiredness is *not* re-derived from the qualifiers: it comes from
    ``__required_keys__``, which the class computes and which stays correct under
    inheritance and ``total=False``. So the qualifiers are simply stripped, and
    ``ReadOnly`` with them, having no runtime meaning at all.
    """
    fields: list[tuple[str, Any]] = []
    for name, ann in t.__annotations__.items():
        fields.append((name, strip_qualifiers(resolve(ann, t))))
    return fields


_INLINE_FORWARD_REF_REASON = (
    "A forward reference written inline records no module and no owner, so "
    "there is nothing to resolve it against. Use a PEP 695 type alias instead: "
    "'type JSON = int | list[JSON]', which is lazily evaluated and resolves "
    "against the module that defines it."
)

_CALLABLE_REASON = (
    "Callability is checkable; signatures are not, in general. Checking only "
    "callable(val) while ignoring the signature would be a totality violation "
    "dressed as support."
)

_NON_RUNTIME_PROTOCOL_REASON = (
    "Protocol is not runtime-checkable: isinstance against it raises. Decorate "
    "it with @typing.runtime_checkable."
)

_TYPE_ARG_REASON = (
    "Type[T] supports T being a class, a union of classes, or Any. issubclass "
    "cannot express anything else, and this library does not invent a subtype "
    "relation of its own."
)
