"""
    Type inspector object, passed to
    :func:`~typing_validation.validation.can_validate` to determine whether a
    type can be validated (and record detailed type information).
"""

from __future__ import annotations
import collections
import collections.abc as collections_abc
import sys
import typing
from typing import Any, Optional, TypeVar, Union, get_type_hints

if sys.version_info[1] >= 8:
    from typing import Literal
else:
    from typing_extensions import Literal

if sys.version_info[1] >= 9:
    TypeConstructorArgs = Union[
        typing.Tuple[Literal["none"], None],
        typing.Tuple[Literal["any"], None],
        typing.Tuple[Literal["type"], type],
        typing.Tuple[
            Literal["type"], typing.Tuple[type, Literal["tuple"], Optional[int]]
        ],
        typing.Tuple[
            Literal["type"], typing.Tuple[type, Literal["mapping"], None]
        ],
        typing.Tuple[
            Literal["type"], typing.Tuple[type, Literal["collection"], None]
        ],
        typing.Tuple[Literal["literal"], typing.Tuple[Any, ...]],
        typing.Tuple[Literal["collection"], None],
        typing.Tuple[Literal["mapping"], None],
        typing.Tuple[Literal["typed-dict"], type],
        typing.Tuple[Literal["typevar"], TypeVar],
        typing.Tuple[Literal["union"], tuple[int, bool]],
        typing.Tuple[Literal["tuple"], Optional[int]],
        typing.Tuple[Literal["user-class"], Optional[int]],
        typing.Tuple[Literal["alias"], str],
        typing.Tuple[Literal["unsupported"], Any],
    ]
else:
    TypeConstructorArgs = typing.Tuple[str, Any]

if sys.version_info[1] >= 10:
    from types import UnionType
else:
    UnionType = None

if sys.version_info[1] >= 11:
    from typing import Self
else:
    from typing_extensions import Self

_typing_equiv = {
    list: typing.List,
    tuple: typing.Tuple,
    set: typing.Set,
    frozenset: typing.FrozenSet,
    dict: typing.Dict,
    collections.deque: typing.Deque,
    collections.defaultdict: typing.DefaultDict,
    collections_abc.Collection: typing.Collection,
    collections_abc.Set: typing.AbstractSet,
    collections_abc.MutableSet: typing.MutableSet,
    collections_abc.Sequence: typing.Sequence,
    collections_abc.MutableSequence: typing.MutableSequence,
    collections_abc.Iterable: typing.Iterable,
    collections_abc.Iterator: typing.Iterator,
    collections_abc.Container: typing.Container,
    collections_abc.Mapping: typing.Mapping,
    collections_abc.MutableMapping: typing.MutableMapping,
    collections_abc.Hashable: typing.Hashable,
    collections_abc.Sized: typing.Sized,
}

if sys.version_info[1] <= 11:
    _typing_equiv[collections_abc.ByteString] = typing.ByteString  # type: ignore


def _to_typing_equiv(t: Any) -> Any:
    if sys.version_info[1] <= 8 and t in _typing_equiv:
        return _typing_equiv[t]
    return t


class UnsupportedType(type):
    r"""
    Wrapper for an unsupported type encountered by a :class:`TypeInspector` instance during validation.
    """

    def __class_getitem__(mcs, wrapped_type: Any) -> "UnsupportedType":
        wrapper = type.__new__(
            mcs, f"{mcs.__name__}[{wrapped_type}]", tuple(), {}
        )
        wrapper._wrapped_type = wrapped_type
        return wrapper

    _wrapped_type: Any

    @property
    def wrapped_type(cls) -> Any:
        r"""The underlying type."""
        return cls._wrapped_type


class TypeInspector:
    r"""
    Class used to record the structure of a type during a call to
    :func:`~typing_validation.validation.can_validate`.
    """

    _recorded_constructors: typing.List[TypeConstructorArgs]
    _unsupported_types: typing.List[Any]
    _pending_generic_type_constr: Optional[TypeConstructorArgs]

    __slots__ = (
        "__weakref__",
        "_recorded_constructors",
        "_unsupported_types",
        "_pending_generic_type_constr",
    )

    def __new__(cls) -> Self:
        instance = super().__new__(cls)
        instance._recorded_constructors = []
        instance._unsupported_types = []
        instance._pending_generic_type_constr = None
        return instance

    @property
    def recorded_type(self) -> Any:
        r"""The type recorded by this type inspector during validation."""
        t, idx = self._recorded_type(0)
        assert (
            idx == len(self._recorded_constructors) - 1
        ), f"The following recorded types have not been included: {self._recorded_constructors[idx+1:]}"
        return t

    @property
    def unsupported_types(self) -> typing.Tuple[Any, ...]:
        r"""The sequence of unsupported types encountered during validation."""
        return tuple(self._unsupported_types)

    @property
    def type_structure(self) -> str:
        """
        The structure of the recorded type:

        1. The string spans multiple lines, with indentation levels matching
           the nesting level of inner types.
        2. Any unsupported types encountered are wrapped using the generic type
           :obj:`UnsupportedType`.

        """
        return "\n".join(self._repr()[0])

    @property
    def type_annotation(self) -> str:
        """
        The type annotation for the recorded type.
        Differs from the output of :attr:`type_structure` in the following ways:

        1. The annotation is on a single line.
        2. Unsupported types are not wrapped.

        """
        return "".join(
            line.strip() for line in self._repr(mark_unsupported=False)[0]
        )

    def _recorded_type(self, idx: int) -> typing.Tuple[Any, int]:
        # pylint: disable = too-many-return-statements, too-many-branches
        param: Any
        tag, param = self._recorded_constructors[idx]
        if tag == "unsupported":
            return UnsupportedType[param], idx  # type: ignore
        if tag == "none":
            return None, idx
        if tag == "any":
            return Any, idx
        if tag == "alias":
            return param, idx
        if tag == "literal":
            assert isinstance(param, tuple)
            # return Literal.__getitem__(Literal, *param), idx
            return (
                Literal.__getitem__(param),
                idx,
            )  # pylint: disable = unnecessary-dunder-call
        if tag == "union":
            assert isinstance(param, tuple)
            num_members, use_UnionType = param
            assert isinstance(num_members, int)
            member_ts: typing.List[Any] = []
            for _ in range(num_members):
                member_t, idx = self._recorded_type(idx + 1)
                member_ts.append(member_t)
            if not use_UnionType:
                return typing.Union.__getitem__(tuple(member_ts)), idx
            union_type = member_ts[0]
            for t in member_ts[1:]:
                union_type |= t
            return union_type, idx
        if tag == "typed-dict":
            for _ in get_type_hints(param):
                _, idx = self._recorded_type(idx + 1)
            return param, idx
        pending_type = None
        if tag == "type":
            # if isinstance(param, type):
            if not isinstance(param, tuple):
                return _to_typing_equiv(param), idx
            pending_type, tag, param = param
        pending_type = _to_typing_equiv(pending_type)
        if tag == "collection":
            item_t, idx = self._recorded_type(idx + 1)
            t = pending_type[item_t] if pending_type is not None else typing.Collection[item_t]  # type: ignore[valid-type]
            return t, idx
        if tag == "mapping":
            key_t, idx = self._recorded_type(idx + 1)
            value_t, idx = self._recorded_type(idx + 1)
            t = pending_type[key_t, value_t] if pending_type is not None else typing.Mapping[key_t, value_t]  # type: ignore[valid-type]
            return t, idx
        if tag == "tuple":
            if param is None:
                item_t, idx = self._recorded_type(idx + 1)
                t = (
                    pending_type[item_t, ...]
                    if pending_type is not None
                    else typing.Tuple[item_t, ...]
                )
                return t, idx
            assert isinstance(param, int)
            item_ts: typing.List[Any] = []
            for _ in range(param):
                item_t, idx = self._recorded_type(idx + 1)
                item_ts.append(item_t)
            if not item_ts:
                item_ts = [tuple()]
            t = (
                pending_type[tuple(item_ts)]
                if pending_type is not None
                else typing.Tuple[tuple(item_ts)]
            )
            return t, idx
        if tag == "user-class":
            assert isinstance(param, int)
            assert pending_type is not None
            item_ts = []
            for _ in range(param):
                item_t, idx = self._recorded_type(idx + 1)
                item_ts.append(item_t)
            if not item_ts:
                item_ts = [tuple()]
            t = pending_type[tuple(item_ts)]
            return t, idx
        assert False, f"Invalid type constructor tag: {repr(tag)}"

    def _append_constructor_args(self, args: TypeConstructorArgs) -> None:
        pending_generic_type_constr = self._pending_generic_type_constr
        if pending_generic_type_constr is None:
            self._recorded_constructors.append(args)
            return
        pending_tag, pending_param = pending_generic_type_constr
        args_tag, args_param = args
        assert pending_tag == "type" and isinstance(pending_param, type)
        assert args_tag in (
            "tuple",
            "mapping",
            "collection",
            "user-class",
        ), (
            f"Found unexpected tag '{args_tag}' with "
            f"type constructor {pending_generic_type_constr} pending."
        )
        if sys.version_info[1] >= 9:
            self._recorded_constructors.append(
                typing.cast(
                    TypeConstructorArgs,
                    ("type", (pending_param, args_tag, args_param)),
                )
            )
        else:
            self._recorded_constructors.append(
                ("type", (pending_param, args_tag, args_param))
            )
        self._pending_generic_type_constr = None

    def _record_none(self) -> None:
        self._append_constructor_args(("none", None))

    def _record_any(self) -> None:
        self._append_constructor_args(("any", None))

    def _record_type(self, t: type) -> None:
        self._append_constructor_args(("type", t))

    def _record_typed_dict(self, t: type) -> None:
        self._append_constructor_args(("typed-dict", t))

    def _record_typevar(self, t: TypeVar) -> None:
        self._append_constructor_args(("typevar", t))

    def _record_pending_type_generic(self, t: type) -> None:
        assert self._pending_generic_type_constr is None
        self._pending_generic_type_constr = ("type", t)

    def _record_collection(self, item_t: Any) -> None:
        self._append_constructor_args(("collection", None))

    def _record_mapping(self, key_t: Any, value_t: Any) -> None:
        self._append_constructor_args(("mapping", None))

    def _record_union(
        self, *member_ts: Any, use_UnionType: bool = False
    ) -> None:
        if use_UnionType:
            assert member_ts, "Cannot use UnionType with empty members."
            assert UnionType is not None, "Cannot use UnionType, version <= 3.9"
        self._append_constructor_args(
            ("union", (len(member_ts), use_UnionType))
        )

    def _record_variadic_tuple(self, item_t: Any) -> None:
        self._append_constructor_args(("tuple", None))

    def _record_fixed_tuple(self, *item_ts: Any) -> None:
        self._append_constructor_args(("tuple", len(item_ts)))

    def _record_user_class(self, *item_ts: Any) -> None:
        self._append_constructor_args(("user-class", len(item_ts)))

    def _record_literal(self, *literals: Any) -> None:
        self._append_constructor_args(("literal", literals))

    def _record_alias(self, t_alias: str) -> None:
        self._append_constructor_args(("alias", t_alias))

    def _record_unsupported_type(self, unsupported_t: Any) -> None:
        self._pending_generic_type_constr = None
        self._unsupported_types.append(unsupported_t)
        self._append_constructor_args(("unsupported", unsupported_t))

    def __bool__(self) -> bool:
        return not self._unsupported_types

    def __repr__(self) -> str:
        """
        Representation of the inspector, including the :attr:`type_structure`.

        :meta public:
        """
        return (
            "TypeInspector instance for the following type:\n"
            + self.type_structure
        )

    def _repr(
        self, idx: int = 0, level: int = 0, *, mark_unsupported: bool = True
    ) -> typing.Tuple[typing.List[str], int]:
        # pylint: disable = too-many-return-statements, too-many-branches, too-many-statements, too-many-locals
        basic_indent = "  "
        assert len(basic_indent) >= 2
        indent = basic_indent * level
        next_indent = basic_indent * (level + 1)
        next_indent_len = len(next_indent)
        param: Any
        lines: typing.List[str]
        tag, param = self._recorded_constructors[idx]
        if tag == "unsupported":
            if not mark_unsupported:
                return [indent + str(param)], idx
            return [
                indent + "UnsupportedType[",
                indent + "    " + str(param),
                indent + "]",
            ], idx
        if tag == "none":
            return [indent + "NoneType"], idx
        if tag == "any":
            return [indent + "Any"], idx
        if tag == "alias":
            return [indent + f"{repr(param)}"], idx
        if tag == "literal":
            assert isinstance(param, tuple)
            return [
                indent + f"Literal[{', '.join(repr(p) for p in param)}]"
            ], idx
        if tag == "typevar":
            assert isinstance(param, TypeVar)
            name = param.__name__
            bound = param.__bound__
            if bound is None:
                lines = [indent + f"TypeVar({name!r})"]
            else:
                bound_lines, idx = self._repr(idx + 1, level + 1)
                lines = [
                    indent + f"TypeVar({name!r}, bound=",
                    *bound_lines,
                    indent + ")",
                ]
            return lines, idx
        if tag == "union":
            assert isinstance(param, tuple)
            num_members, use_UnionType = param
            assert isinstance(num_members, int)
            lines = []
            if not use_UnionType:
                lines.append(indent + "Union[")
            for _ in range(num_members):
                member_lines, idx = self._repr(idx + 1, level + 1)
                if use_UnionType:
                    member_lines[-1] += "|"
                else:
                    member_lines[-1] += ","
                lines.extend(member_lines)
            assert len(lines) > 1, "Cannot take a union of no types."
            if not use_UnionType:
                lines.append(indent + "]")
            return lines, idx
        if tag == "typed-dict":
            t = param
            required_keys: frozenset[str] = getattr(t, "__required_keys__")
            item_lines_list: list[str] = []
            for k in get_type_hints(t):
                value_lines, idx = self._repr(idx + 1, level + 1)
                opt_str = (
                    basic_indent
                    if k in required_keys
                    else basic_indent[:-1] + "?"
                )
                value_lines[0] = (
                    indent
                    + opt_str
                    + f"{k}: "
                    + value_lines[0][next_indent_len:]
                )
                item_lines_list.extend(value_lines)
            lines = [indent + t.__name__ + " {", *item_lines_list, indent + "}"]
            return lines, idx
        pending_type = None
        if tag == "type":
            if not isinstance(param, tuple):
                param_name = (
                    param.__name__ if isinstance(param, type) else str(param)
                )
                return [indent + param_name], idx
            pending_type, tag, param = param
        if tag == "collection":
            item_lines, idx = self._repr(idx + 1, level + 1)
            if pending_type is not None:
                lines = [
                    indent + f"{pending_type.__name__}[",
                    *item_lines,
                    indent + "]",
                ]
            else:
                lines = [indent + "Collection[", *item_lines, indent + "]"]
            return lines, idx
        if tag == "mapping":
            key_lines, idx = self._repr(idx + 1, level + 1)
            key_lines[-1] += ","
            value_lines, idx = self._repr(idx + 1, level + 1)
            if pending_type is not None:
                lines = [
                    indent + f"{pending_type.__name__}[",
                    *key_lines,
                    *value_lines,
                    indent + "]",
                ]
            else:
                lines = [
                    indent + "Mapping[",
                    *key_lines,
                    *value_lines,
                    indent + "]",
                ]
            return lines, idx
        if tag == "tuple":
            if param is None:
                item_lines, idx = self._repr(idx + 1, level + 1)
                item_lines[-1] += ","
                if pending_type is not None:
                    lines = [
                        indent + f"{pending_type.__name__}[",
                        *item_lines,
                        next_indent + "...",
                        indent + "]",
                    ]
                else:
                    lines = [indent + "Tuple[", *item_lines, indent + "]"]
                return lines, idx
            assert isinstance(param, int)
            lines = [
                (
                    indent + f"{pending_type.__name__}["
                    if pending_type is not None
                    else indent + "Tuple["
                )
            ]
            for _ in range(param):
                item_lines, idx = self._repr(idx + 1, level + 1)
                item_lines[-1] += ","
                lines.extend(item_lines)
            if len(lines) == 1:
                lines.append("tuple()")
            lines.append(indent + "]")
            return lines, idx
        if tag == "user-class":
            assert isinstance(param, int)
            assert pending_type is not None
            lines = [indent + f"{pending_type.__name__}["]
            for _ in range(param):
                item_lines, idx = self._repr(idx + 1, level + 1)
                item_lines[-1] += ","
                lines.extend(item_lines)
            if len(lines) == 1:
                lines.append("tuple()")
            lines.append(indent + "]")
            return lines, idx
        assert False, f"Invalid type constructor tag: {repr(tag)}"
