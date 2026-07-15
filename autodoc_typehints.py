"""Autodoc extension to document attributes and signatures based on Python type hints."""

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.

# You should have received a copy of the GNU Lesser General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import annotationlib
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
import functools
import inspect
import re
import traceback
from types import FunctionType, ModuleType
from typing import Any
from sphinx.application import Sphinx
from sphinx.util import logging

logger = logging.getLogger(__name__)

# In conf.py, can use property_descriptors and/or cached_property_descriptors
# to specify descriptor classes which should be documented as (cached) properties.
# For example, the following is in conf.py for the tensorsat project:
# cached_property_descriptors = {"tensorsat._utils.meta.cached_property"}

PROPERTY_DESCRIPTORS: set[str] = set()
CACHED_PROPERTY_DESCRIPTORS: set[str] = set()


### 1. Parse Type Annotations ###


@dataclass(frozen=True)
class ParsedType:
    r"""Dataclass for a parsed type."""

    name: str
    args: None | str | tuple[ParsedType, ...] = None
    variadic: bool = False

    def __post_init__(self) -> None:
        name, args, variadic = self.name, self.args, self.variadic
        assert isinstance(name, str)
        assert isinstance(variadic, bool)
        if args is not None and not isinstance(args, str):
            assert isinstance(args, tuple)
            assert all(isinstance(arg, ParsedType) for arg in args)
        if variadic:
            assert isinstance(args, tuple)
        if "(" in name or ")" in name:
            raise ValueError(
                "Round brackets in type annotations are only supported for "
                "empty type arguments lists, in the form TypeName[()]."
            )
        if isinstance(args, str) and not args:
            raise ValueError("Literal type must include at least one value.")

    def crossref(self, globalns: Mapping[str, Any] | None = None) -> str:
        """Generates Sphinx cross-reference link for the given type, using local names."""
        if globalns is None:
            globalns = {}
        name, args, variadic = self.name, self.args, self.variadic
        role = "obj"
        if name in globalns:
            obj = globalns[name]
            if isinstance(obj, ModuleType):
                role = "mod"
            elif isinstance(obj, property):
                role = "attr"
            elif isinstance(obj, type):
                if name not in ("Any", "typing.Any"):
                    role = "class"
            elif isinstance(obj, FunctionType):
                role = "func"
        name_crossref = f":{role}:`{name}`"
        if args is None:
            return name_crossref
        if name in ("UnionType", "types.UnionType"):
            assert isinstance(args, tuple)
            return " | ".join((arg.crossref(globalns) for arg in args))
        if isinstance(args, str):
            _args = eval(f"({args}, )")
            arg_crossrefs = ", ".join(f"``{repr(arg)}``" for arg in _args)
        elif not args:
            arg_crossrefs = "()"
        else:
            arg_crossrefs = ", ".join((arg.crossref(globalns) for arg in args))
        if variadic:
            arg_crossrefs += ", ..."
        return rf"{name_crossref}\ [{arg_crossrefs}]"

    def _repr(self, level: int = 0) -> list[str]:
        basic_indent = "  "
        indent = basic_indent * level
        next_indent = basic_indent * (level + 1)
        name, args, variadic = self.name, self.args, self.variadic
        if args is None:
            assert not variadic
            return [indent + f"ParsedType({name!r})"]
        lines = [indent + "ParsedType(", next_indent + f"name = {self.name!r},"]
        if isinstance(args, str):
            assert not variadic
            lines.append(next_indent + f"args = {args!r}")
        else:
            assert isinstance(args, tuple)
            if not args:
                assert not variadic
                lines.append(next_indent + "args = ()")
            else:
                lines.append(next_indent + "args = (")
                for i, arg in enumerate(args):
                    assert isinstance(arg, ParsedType)
                    lines.extend(arg._repr(level + 2))
                    sep = "," if i < len(args) - 1 or len(args) == 1 else ""
                    lines[-1] = lines[-1] + sep
                lines.append(next_indent + ")")
        if variadic:
            lines[-1] = lines[-1] + ","
            lines.append(next_indent + "variadic = True")
        lines.append(indent + ")")
        return lines

    def __repr__(self) -> str:
        """Return a structured representation of the parsed type."""
        return "\n".join(self._repr())


def _outer_bracket_ranges(s: str, start: int, stop: int) -> Iterator[range]:
    if stop is None:
        stop = len(s)
    open: int | None = None
    level = 0
    for i in range(start, stop):
        c = s[i]
        if c == "[":
            if open is None:
                assert level == 0
                open = i
            level += 1
        if c == "]":
            if open is None:
                raise ValueError(f"Unbalanced ']' at index {i}.")
            assert level > 0
            level -= 1
            if level == 0:
                yield range(open, i + 1)
                open = None
    if open is not None:
        raise ValueError(f"Unbalanced '[' at index {open}.")


def _find_outside_ranges(
    char: str, s: str, ranges: Iterable[range], start: int, stop: int
) -> Iterator[int]:
    assert len(char) == 1, f"Expected single char, found {s!r}."
    if stop is None:
        stop = len(s)
    ranges = deque(sorted(ranges, key=lambda r: r.start))
    _start = start
    while (char_idx := s.find(char, _start, stop)) >= 0:
        while ranges and ranges[0].stop <= _start:
            ranges.popleft()
        if not ranges or char_idx not in ranges[0]:
            yield char_idx
            _start = char_idx + 1
        else:
            r = ranges.popleft()
            _start = r.stop


def _split_at(idxs: Iterable[int], start: int, stop: int) -> Iterable[range]:
    idxs = sorted(idxs)
    assert all(idx in range(start, stop) for idx in idxs)
    _start = start
    for idx in idxs:
        if idx > _start:
            yield range(_start, idx)
        else:
            assert idx == _start
        _start = idx + 1
    if _start < stop:
        yield range(_start, stop)


def _parsed_type(
    annotation: str,
    start: int,
    stop: int,
    name: str,
    args: None | str | tuple[ParsedType, ...] = None,
    variadic: bool = False,
) -> ParsedType:
    try:
        t = ParsedType(name, args, variadic)
    except ValueError as e:
        raise ValueError(
            "Error parsing type at \n"
            f"{start = }, {stop = }, {annotation[start:stop] = }, {annotation = }.\n"
            f"ValueError: {e}"
        )
    return t


def _parse_type_args(
    annotation: str, start: int, stop: int
) -> tuple[tuple[ParsedType, ...], bool]:
    if annotation[start:stop].strip() == "()":
        return (), False
    bracket_ranges = tuple(_outer_bracket_ranges(annotation, start, stop))
    comma_idxs = tuple(
        _find_outside_ranges(",", annotation, bracket_ranges, start, stop)
    )
    if not comma_idxs:
        return (_parse_type(annotation, start, stop),), False
    arg_ranges = tuple(_split_at(comma_idxs, start, stop))
    args: list[ParsedType] = []
    variadic = False
    for i, r in enumerate(arg_ranges):
        arg = _parse_type(annotation, r.start, r.stop)
        if arg.name == "...":
            if i < len(arg_ranges) - 1:
                raise ValueError(
                    "Ellipsis found in args, but not in last position, at "
                    f"{start = }, {stop = }, {annotation[start:stop] = }, {annotation = }"
                )
            variadic = True
            break
        args.append(arg)
    return tuple(args), variadic


def _parse_atom_type(annotation: str, start: int, stop: int) -> ParsedType:
    while start < stop and annotation[start].isspace():
        start += 1
    while start < stop and annotation[stop - 1].isspace():
        stop -= 1
    assert annotation[start:stop] == annotation[start:stop].strip()
    bracket_ranges = tuple(_outer_bracket_ranges(annotation, start, stop))
    if len(bracket_ranges) > 1:
        raise ValueError(
            "Non-union type must take the form 'TypeName' or 'TypeName[Args]'. "
            f"Found multiple outer bracket pairs at "
            f"{start = }, {stop = }, {annotation[start:stop] = }, {annotation = }"
        )
    r = bracket_ranges[0] if bracket_ranges else None
    if r is None:
        name = annotation[start:stop].strip()
        return _parsed_type(annotation, start, stop, name)
    elif r.stop < stop:
        raise ValueError(
            "Non-union type must take the form 'TypeName' or 'TypeName[Args]'. "
            "Found text after bracket pair at "
            f"{start = }, {stop = }, {annotation[start:stop] = }, {annotation = }"
        )
    name = annotation[start : r.start].strip()
    if name in ("Literal", "typing.Literal"):
        return _parsed_type(
            annotation, start, stop, name, annotation[r.start + 1 : r.stop - 1]
        )
    if not name:
        raise ValueError(
            f"Found empty type name at "
            f"{start = }, {stop = }, {annotation[start:stop] = }, {annotation = }"
        )
    args, variadic = _parse_type_args(annotation, r.start + 1, r.stop - 1)
    return _parsed_type(annotation, start, stop, name, args, variadic)


def _parse_type(annotation: str, start: int, stop: int) -> ParsedType:
    bracket_ranges = tuple(_outer_bracket_ranges(annotation, start, stop))
    ors_idxs = tuple(_find_outside_ranges("|", annotation, bracket_ranges, start, stop))
    if not ors_idxs:
        return _parse_atom_type(annotation, start, stop)
    member_ranges = tuple(_split_at(ors_idxs, start, stop))
    name = "UnionType"
    args = tuple(_parse_atom_type(annotation, r.start, r.stop) for r in member_ranges)
    return _parsed_type(annotation, start, stop, name, args)


def parse_type(annotation: str) -> ParsedType:
    return _parse_type(annotation, 0, len(annotation))


### 2. Track Classes Known to Autodoc ###

_class_dict: dict[str, type] = {}


def class_tracking_handler(
    app: Sphinx,
    what: str,
    fullname: str,
    obj: Any,
    options: Any,
    lines: list[str],
) -> None:
    """
    Keeps track of classes known to autodoc, for use in other handlers.

    Handler for Sphinx Autodoc's event
    `autodoc-process-docstring <https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html#event-autodoc-process-docstring>`_
    """
    if what != "class":
        return
    _class_dict[fullname] = obj
    if fullname in PROPERTY_DESCRIPTORS:
        obj.__bases__ += (property,)
    elif fullname in CACHED_PROPERTY_DESCRIPTORS:
        obj.__bases__ += (functools.cached_property,)


### 3. Document Function Parameter and Return Types ###


def _sigdoc(fun: FunctionType, lines: list[str]) -> None:
    """Return doclines documenting parameter/return types for the given function."""
    doc = "\n".join(lines)
    lines.append("")
    # FIXME: if an :rtype: line already exists, remove it here and re-append it after all param type lines.
    globalns = fun.__globals__
    sig = inspect.signature(fun, annotation_format=annotationlib.Format.STRING)
    for p in sig.parameters.values():
        annotation = p.annotation
        if annotation == p.empty:
            continue
        if not isinstance(annotation, str):
            # STRING-format signatures yield string annotations; coerce anything
            # unexpected rather than failing.
            logger.warning(f"Found non-string annotation: {annotation!r}.")
            annotation = str(annotation)
        try:
            t = parse_type(annotation)
            tx = t.crossref(globalns)
        except Exception as e:
            logger.error(
                f"Parsing param {p.name!r} type annotation {annotation!r},"
                f" {type(e)}: {e}"
            )
            tx = annotation
        default = p.default if p.default != p.empty else None
        is_args = p.kind == p.VAR_POSITIONAL
        is_kwargs = p.kind == p.VAR_KEYWORD
        if is_args:
            extra_info = "variadic positional"
        elif is_kwargs:
            extra_info = "variadic keyword"
        elif default is not None:
            default_str = (
                default.__qualname__
                if isinstance(default, FunctionType)
                else repr(default)
            )
            extra_info = f"default = ``{default_str}``"
        else:
            extra_info = None
        if extra_info is None:
            line = f":type {p.name}: {tx}"
        else:
            line = f":type {p.name}: {tx}; {extra_info}"
        if f":param {p.name}:" not in doc:
            lines.append(f":param {p.name}:")
        if f":type {p.name}:" not in doc:
            lines.append(line)
    if sig.return_annotation == sig.empty:
        return

    try:
        t = parse_type(sig.return_annotation)
        tx = t.crossref(globalns)
    except Exception as e:
        logger.error(
            f"Parsing return type annotation {annotation!r}," f" {type(e)}: {e}"
        )
        tx = annotation
    line = f":rtype: {tx}"
    if ":rtype:" not in doc:
        lines.append(line)


def signature_doc_handler(
    app: Sphinx,
    what: str,
    fullname: str,
    obj: Any,
    options: Any,
    lines: list[str],
) -> None:
    """
    Automatically documents parameter/return types for functions, methods and properties.

    Handler for Sphinx Autodoc's event
    `autodoc-process-docstring <https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html#event-autodoc-process-docstring>`_
    """
    if what not in ("function", "method", "property"):
        return
    if what == "property":
        fun: FunctionType = obj.fget
    else:
        fun = obj
    try:
        _sigdoc(fun, lines)
    except Exception as e:
        msg = (
            f"In signature_doc_handler(app, {what = }, {fullname = }, ...),"
            f" raised {type(e)}: {e}"
        )
        logger.error(msg)


### 4. Document Attribute Types ###


def attr_doc_handler(
    app: Sphinx,
    what: str,
    fullname: str,
    obj: Any,
    options: Any,
    lines: list[str],
) -> None:
    r"""
    Automatically documents the type of attributes.

    Handler for Sphinx Autodoc's event
    `autodoc-process-docstring <https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html#event-autodoc-process-docstring>`_
    """
    if what != "attribute":
        return
    try:
        attrname = fullname.split(".")[-1]
        classname = ".".join(fullname.split(".")[:-1])
        parent_class = _class_dict.get(classname)
        if parent_class is not None:
            annotations = annotationlib.get_annotations(
                parent_class, format=annotationlib.Format.STRING
            )
            if attrname in annotations:
                type_annotation = annotations[attrname]
            else:
                type_annotation = None
            if type_annotation is not None:
                if not isinstance(type_annotation, str):
                    # STRING-format annotations are strings; coerce anything
                    # unexpected rather than failing.
                    logger.warning(f"Found non-string annotation: {type_annotation!r}.")
                    type_annotation = str(type_annotation)
                t = parse_type(type_annotation)
                tx = t.crossref()
                if ":rtype:" not in "\n".join(lines):
                    lines.append(f":rtype: {tx}")
    except Exception as e:
        tb_str = "\n".join(traceback.format_tb(e.__traceback__))
        msg = (
            f"In attr_doc_handler(app, {what = }, {fullname = }, ...),"
            f" raised {type(e)}: {e}\n{tb_str}"
        )
        logger.error(msg)


### 5. Replace Cross-references with Fully Qualified Names ###


def simple_crossref_pattern(name: str) -> re.Pattern[str]:
    """
    Pattern for simple imports:

    .. code-block :: python

        f":{role}:`{name}`"        # e.g. ":class:`MyClass`"
        f":{role}:`~{name}`"       # e.g. ":class:`~MyClass`"
        f":{role}:`{name}{tail}`"  # e.g. ":attr:`MyClass.my_property.my_subproperty`"
        f":{role}:`~{name}{tail}`" # e.g. ":attr:`~MyClass.my_property.my_subproperty`"

    """
    return re.compile(rf":([a-z]+):`(~)?{name}(\.[\.a-zA-Z0-9_]+)?`")


def simple_crossref_repl(name: str, fullname: str) -> Callable[[re.Match[str]], str]:
    """
    Replacement function for the pattern generated by :func:`simple_crossref_pattern`:

    .. code-block :: python

        f":{role}:`~{fullname}`"                    # e.g. ":class:`~mymod.mysubmod.MyClass`"
        f":{role}:`~{fullname}`"                    # e.g. ":class:`~mymod.mysubmod.MyClass`"
        f":{role}:`{name}{tail}<{fullname}{tail}>`" # e.g. ":attr:`MyClass.my_property.my_subproperty<mymod.mysubmod.MyClass.my_property.my_subproperty>`"
        f":{role}:`~{fullname}{tail}`"              # e.g. ":attr:`~mymod.mysubmod.MyClass.my_property.my_subproperty`"

    """

    def repl(match: re.Match[str]) -> str:
        role = match[1]
        short = match[2] is not None
        tail = match[3]
        if tail is None:
            return f":{role}:`~{fullname}`"
        if short:
            return f":{role}:`~{fullname}{tail}`"
        return f":{role}:`{name}{tail}<{fullname}{tail}>`"

    return repl


def labelled_crossref_pattern(name: str) -> re.Pattern[str]:
    """
    Pattern for labelled imports:

    .. code-block :: python

        f":{role}:`{label}<{name}>`"       # e.g. ":class:`my class<MyClass>`"
        f":{role}:`{label}<{name}{tail}>`" # e.g. ":attr:`my_property<MyClass.my_property>`"

    """
    return re.compile(rf":([a-z]+):`([\.a-zA-Z0-9_]+)<{name}(\.[\.a-zA-Z0-9_]+)?>`")


def labelled_crossref_repl(name: str, fullname: str) -> Callable[[re.Match[str]], str]:
    """
    Replacement function for the pattern generated by :func:`labelled_crossref_pattern`:

    .. code-block :: python

        f":{role}:`{label}<{fullname}>`"       # e.g. ":class:`my class<mymod.mysubmod.MyClass>`"
        f":{role}:`{label}<{fullname}{tail}>`" # e.g. ":attr:`my_property<mymod.mysubmod.MyClass.my_property>`"

    """

    def repl(match: re.Match[str]) -> str:
        role = match[1]
        label = match[2]
        tail = match[3]
        if tail is None:
            return f":{role}:`{label}<{fullname}>`"
        return f":{role}:`{label}<{fullname}{tail}>`"

    return repl


_crossref_subs: list[
    tuple[
        Callable[[str], re.Pattern[str]],
        Callable[[str, str], Callable[[re.Match[str]], str]],
    ]
] = [
    (simple_crossref_pattern, simple_crossref_repl),
    (labelled_crossref_pattern, labelled_crossref_repl),
]
"""
Substitution patterns and replacement functions for various kinds of cross-reference scenarios.
"""


def _get_module_by_name(modname: str) -> ModuleType:
    """Gathers a module object by name."""
    namespace: dict[str, Any] = {}
    exec(f"import {modname} as _mymodule", namespace)
    mod: ModuleType = namespace["_mymodule"]
    if not isinstance(mod, ModuleType):
        return None
    return mod


def _get_obj_mod(app: Sphinx, what: str, fullname: str, obj: Any) -> ModuleType | None:
    """Gathers the containing module for the given ``obj``."""
    autodoc_type_aliases = app.config.__dict__.get("autodoc_type_aliases")
    name = fullname.split(".")[-1]
    obj_mod: ModuleType | None
    if autodoc_type_aliases is not None:
        if name in autodoc_type_aliases and fullname == autodoc_type_aliases[name]:
            modname = ".".join(fullname.split(".")[:-1])
            obj_mod = _get_module_by_name(modname)
            return obj_mod
    if what == "module":
        obj_mod = obj
    elif what in ("function", "class", "method", "exception"):
        obj_mod = inspect.getmodule(obj)
    elif what == "property":
        obj_mod = inspect.getmodule(obj.fget)
    elif what == "data":
        modname = ".".join(fullname.split(".")[:-1])
        obj_mod = _get_module_by_name(modname)
    elif what == "attribute":
        modname = ".".join(fullname.split(".")[:-2])
        obj_mod = _get_module_by_name(modname)
    else:
        logger.warning(
            f"Encountered unexpected value for what = {what} at fullname = {fullname}"
        )
        obj_mod = None
    return obj_mod


def _build_fullname_dict(
    app: Sphinx,
    fullname: str,
    obj_mod: ModuleType | None,
) -> dict[str, str]:
    """
    Builds a dictionary of substitutions from module global names to their fully qualified names,
    based on :func:`inspect.getmodule` and `autodoc_type_aliases`
    (if specified in the Sphinx app config).
    """
    autodoc_type_aliases = app.config.__dict__.get("autodoc_type_aliases")
    fullname_dict: dict[str, str] = {}
    if obj_mod is not None:
        globalns = obj_mod.__dict__
        for g_name, g_obj in globalns.items():
            if isinstance(g_obj, (FunctionType, type)):
                g_mod = inspect.getmodule(g_obj)
            elif isinstance(g_obj, ModuleType):
                g_mod = g_obj
            else:
                g_mod = inspect.getmodule(g_obj)
            if g_mod is None or g_mod == obj_mod:
                continue
            if g_name not in g_mod.__dict__:
                continue
            g_modname = g_mod.__name__
            fullname_dict[g_name] = f"{g_modname}.{g_name}"
    if autodoc_type_aliases is not None:
        for a_name, a_fullname in autodoc_type_aliases.items():
            if a_name not in fullname_dict:
                fullname_dict[a_name] = a_fullname
    return fullname_dict


def local_crossref_handler(
    app: Sphinx,
    what: str,
    fullname: str,
    obj: Any,
    options: Any,
    lines: list[str],
) -> None:
    """
    Replaces cross-references specified in terms of module globals with their fully qualified version.

    Handler for Sphinx Autodoc's event
    `autodoc-process-docstring <https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html#event-autodoc-process-docstring>`_
    """
    obj_mod = _get_obj_mod(app, what, fullname, obj)
    fullname_dict = _build_fullname_dict(app, fullname, obj_mod)
    for sub_name, sub_fullname in fullname_dict.items():
        for idx, line in enumerate(lines):
            for pattern_fun, repl_fun in _crossref_subs:
                pattern = pattern_fun(sub_name)
                repl = repl_fun(sub_name, sub_fullname)
                line = re.sub(pattern, repl, line)
            lines[idx] = line


def on_config_inited(app: Sphinx, _: Any) -> None:
    """Updates data structures based on app.config (conf.py)."""
    PROPERTY_DESCRIPTORS.update(app.config.property_descriptors)
    CACHED_PROPERTY_DESCRIPTORS.update(app.config.cached_property_descriptors)


### 6. Register Sphinx Event Handlers ###


def setup(app: Sphinx) -> None:
    """Registers handlers for Sphinx events."""
    app.add_config_value("property_descriptors", default=set(), rebuild="env")
    app.add_config_value("cached_property_descriptors", default=set(), rebuild="env")
    app.connect("config-inited", on_config_inited)

    app.connect("autodoc-process-docstring", class_tracking_handler)
    app.connect("autodoc-process-docstring", signature_doc_handler)
    app.connect("autodoc-process-docstring", attr_doc_handler)
    app.connect("autodoc-process-docstring", local_crossref_handler)
