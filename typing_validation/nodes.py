# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The node model: one interned node per distinct type, holding the type it was
built from, its form, its interned children, and its memoised properties.

Everything except :func:`~typing_validation.validate` is built on this one
class. It is simultaneously the unit of interning, the thing
:func:`~typing_validation.inspect_type` reports, the thing that will emit a
closure in 2.1, the thing that will emit source in 2.2, and the thing that
explains a failure. It can be all of those at once precisely because none of
them is on a hot path — which is also why this module may share freely with
them, and why it shares nothing with the interpreter.
"""

import enum
import typing
from collections import defaultdict, deque
from collections.abc import Callable as abc_Callable
from collections.abc import (
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
    Literal,
    Self,
    TypeVar,
    Union,
    final,
    is_typeddict,
)

from annotationlib import ForwardRef

from .plugins import (
    plugin_import,
    registered_components,
    registered_validator,
    unsupported_explanation,
)
from .resolution import resolve, strip_qualifiers

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
    """A mapping whose keys and values are each checked against a type argument."""

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
    """A :func:`~typing.NewType`, validated as its supertype."""

    ITERATOR = "iterator"
    """An iterator, whose items cannot be checked without consuming it."""

    MAYBE_ITEMS = "iterable or container"
    """
    An iterable or container, whose items are checked only when the value is
    also a :class:`~collections.abc.Collection`.
    """

    UNSUPPORTED = "unsupported"
    """A type this library cannot validate against. Poisons whatever contains it."""


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
_BYTESTRING_ORIGIN = typing.get_origin(typing.ByteString)


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

    __slots__ = ("_t", "_form", "_children", "_labels", "_supported", "_reason")

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
        return f"<TypeNode {self._t!r}: {self._form.value}{mark}>"


_TIERS: list[dict[Any, TypeNode]] = [{}]
"""
The intern cache, innermost tier last.

By default the cache lives forever and holds strong references, because types
are usually module-level objects that outlive any cache anyway. Scoped caching
pushes a tier; lookups consult the tiers innermost-first; every new node is
created in the innermost tier; exiting drops that tier whole, in one operation,
with no per-entry bookkeeping.

The tiering is sound because **references only ever point outward**. A node
created while a tier is active lives in that tier and may reference nodes in
enclosing tiers, which outlive it. Nothing in an enclosing tier can reference
into an inner one, because while the inner tier is active it is where all new
nodes go. So dropping a tier can never leave a dangling reference behind it —
and can never change an answer, only a cost.
"""


def _lookup(t: Any, /) -> TypeNode | None:
    for tier in reversed(_TIERS):
        node = tier.get(t)
        if node is not None:
            return node
    return None


def node_for(t: Any, /) -> TypeNode:
    """
    The interned node for a type, building it if it is not already cached.

    :param t: the type to analyse.
    """
    fresh: list[TypeNode] = []
    node = _build(t, fresh)
    _settle_support(fresh)
    return node


def _build(t: Any, fresh: list[TypeNode], /) -> TypeNode:
    """
    Intern a node for a type, then build its children.

    **Hash-cons before descending**: the node is published *before* its children
    exist, so a back-edge finds the in-progress node and construction
    terminates. A cycle can only close through a name — a PEP 695 alias or a
    forward reference — and names are always hashable, so a cycle root is always
    in the cache, even when unhashable leaves sit inside the cycle.
    """
    try:
        cached = _lookup(t)
    except TypeError:
        # Unhashable, and so unshareable: Annotated[int, {"ge": 0}] is exactly
        # the pydantic-style idiom the Annotated decision exists to accommodate,
        # so this is not a corner case. It builds a fresh node, forgoes sharing,
        # and remains fully supported. Interning is an optimisation; skipping it
        # may cost, and may not change an answer.
        node = TypeNode(t)
        fresh.append(node)
        _analyse(node, fresh)
        return node
    if cached is not None:
        return cached
    node = TypeNode(t)
    _TIERS[-1][t] = node
    fresh.append(node)
    _analyse(node, fresh)
    return node


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


def _unsupported(node: TypeNode, reason: str | None = None, /) -> None:
    node._form = TypeForm.UNSUPPORTED
    node._supported = False
    node._reason = reason


def _analyse(node: TypeNode, fresh: list[TypeNode], /) -> None:
    """
    Determine a node's form and build its children.

    This duplicates the interpreter's dispatch, deliberately and by design: the
    two share a specification rather than an implementation. Here the shape is
    chosen for clarity, because nothing on this path is hot; there it is chosen
    for speed. The conformance suite is what keeps them agreeing.

    Recursion is safe here in a way it is not in the interpreter, because this
    walks the *type*, which is shallow, rather than the *value*, which is not.
    """
    t = node._t
    tt = type(t)

    if t is Any:
        node._form = TypeForm.ANY
        return
    if t is None or t is type(None):
        node._form = TypeForm.NONE
        return
    if t is typing.NamedTuple:
        node._form = TypeForm.ANY_NAMED_TUPLE
        return
    if tt is typing.TypeAliasType:
        node._form = TypeForm.ALIAS
        node._children = (_build(t.__value__, fresh),)
        return
    if tt is TypeVar:
        node._form = TypeForm.TYPE_VAR
        if t.__bound__ is not None:
            node._children = (_build(t.__bound__, fresh),)
        elif t.__constraints__:
            node._children = (_build(Union[t.__constraints__], fresh),)
        return
    if tt is typing.NewType:
        node._form = TypeForm.NEW_TYPE
        node._children = (_build(t.__supertype__, fresh),)
        return
    if isinstance(t, (str, ForwardRef)):
        _unsupported(node, _INLINE_FORWARD_REF_REASON)
        return

    if tt is type or isinstance(t, type):
        _analyse_class(node, t, fresh)
        return

    if tt is GenericAlias:
        origin = t.__origin__
        args: tuple[Any, ...] = t.__args__
    elif tt is Union:  # type: ignore[comparison-overlap]
        origin = Union
        args = t.__args__
    else:
        origin = typing.get_origin(t)
        args = typing.get_args(t)

    if origin is None:
        _unsupported(node)
    elif origin is Union:
        node._form = TypeForm.UNION
        node._children = tuple(_build(arg, fresh) for arg in args)
    elif origin is Literal:
        # The children of a Literal are values, not types, so it has none.
        node._form = TypeForm.LITERAL
    elif origin is Annotated:
        # Not stripped: Annotated[int, Ge(0)] is a distinct type from int, keeps
        # its own identity and its own cache entry, and reports as written.
        node._form = TypeForm.ANNOTATED
        node._children = (_build(t.__origin__, fresh),)
    elif origin in _COLLECTION_ORIGINS:
        node._form = TypeForm.COLLECTION
        node._children = tuple(_build(arg, fresh) for arg in args[:1])
    elif origin in _MAPPING_ORIGINS:
        node._form = TypeForm.MAPPING
        node._children = tuple(_build(arg, fresh) for arg in args[:2])
        if node._children:
            node._labels = ("key", "value")
    elif origin is tuple:
        _analyse_tuple(node, t, args, fresh)
    elif origin is type:
        _analyse_type_of(node, t, args, fresh)
    elif origin in _ITERATOR_ORIGINS:
        node._form = TypeForm.ITERATOR
    elif origin in _MAYBE_ITEM_ORIGINS:
        node._form = TypeForm.MAYBE_ITEMS
        node._children = tuple(_build(arg, fresh) for arg in args[:1])
    elif origin is _BYTESTRING_ORIGIN:
        node._form = TypeForm.CLASS
    elif origin is abc_Callable:
        _unsupported(node, _CALLABLE_REASON)
    elif type(origin) is typing.TypeAliasType:
        node._form = TypeForm.ALIAS
        node._children = (_build(origin.__value__[args], fresh),)
    elif isinstance(origin, type):
        _analyse_parametrised_class(node, t, origin, args, fresh)
    else:
        _unsupported(node)


def _analyse_class(node: TypeNode, t: Any, fresh: list[TypeNode], /) -> None:
    if is_typeddict(t):
        node._form = TypeForm.TYPED_DICT
        names: list[str] = []
        children: list[TypeNode] = []
        for name, ann in _typed_dict_fields(t):
            names.append(name)
            children.append(_build(ann, fresh))
        node._labels = tuple(names)
        node._children = tuple(children)
        return
    if typing.is_protocol(t):
        if not getattr(t, "_is_runtime_protocol", False):
            _unsupported(node, _NON_RUNTIME_PROTOCOL_REASON)
            return
        node._form = TypeForm.PROTOCOL
        return
    if issubclass(t, tuple) and getattr(t, "_fields", None) is not None:
        node._form = TypeForm.NAMED_TUPLE
        names = []
        children = []
        annotations = getattr(t, "__annotations__", {})
        for name in t._fields:
            ann = annotations.get(name)
            if ann is None:
                continue
            names.append(name)
            children.append(_build(resolve(ann, t), fresh))
        node._labels = tuple(names)
        node._children = tuple(children)
        return
    node._form = TypeForm.CLASS


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


def _analyse_tuple(
    node: TypeNode, t: Any, args: tuple[Any, ...], fresh: list[TypeNode], /
) -> None:
    node._form = TypeForm.TUPLE
    if not args:
        # Bare typing.Tuple means any tuple; tuple[()] means the empty tuple.
        # Both record no arguments, so only the spelling tells them apart.
        if t is typing.Tuple:
            node._form = TypeForm.CLASS
        return
    if len(args) == 2 and args[1] is Ellipsis:
        node._children = (_build(args[0], fresh),)
        return
    node._children = tuple(_build(arg, fresh) for arg in args)


def _analyse_type_of(
    node: TypeNode, t: Any, args: tuple[Any, ...], fresh: list[TypeNode], /
) -> None:
    node._form = TypeForm.TYPE_OF
    if not args:
        return
    (arg,) = args
    if arg is Any or type(arg) is type:
        node._children = (_build(arg, fresh),)
        return
    if type(arg) is Union:  # type: ignore[comparison-overlap]
        for member in arg.__args__:
            if type(member) is not type:
                _unsupported(node, _TYPE_ARG_REASON)
                return
        node._children = (_build(arg, fresh),)
        return
    _unsupported(node, _TYPE_ARG_REASON)


def _analyse_parametrised_class(
    node: TypeNode,
    t: Any,
    origin: type,
    args: tuple[Any, ...],
    fresh: list[TypeNode],
    /,
) -> None:
    check = getattr(origin, "__validate__", None)
    if check is None:
        check = registered_validator(origin)
    if check is None:
        if plugin_import(origin) is not None:
            _unsupported(node, unsupported_explanation(origin))
            return
        # The arguments go unchecked, which is the specified meaning of a
        # generic class rather than a shortfall, so they are not children: a
        # child is a component that bears on the verdict. They are still visible
        # on the type itself.
        node._form = TypeForm.GENERIC_CLASS
        return
    node._form = TypeForm.PLUGIN
    # Only the arguments the plugin *declares* as components are children, and
    # only they propagate totality. The core cannot tell which of a plugin's
    # arguments it validates and which are specifications the plugin interprets:
    # numpy.ndarray[shape, dtype] has one of each, and treating the dtype as a
    # component would poison every array type, since numpy.dtype[numpy.uint8] is
    # itself a parametrised numpy class with no validator of its own.
    components = registered_components(origin)
    if components is not None:
        node._children = tuple(_build(c, fresh) for c in components(args))


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
