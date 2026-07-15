# SPDX-License-Identifier: LGPL-3.0-or-later

"""
House style that a formatter cannot enforce.

``black`` settles almost everything, but it has no opinion on blank lines
*within* a function body — and where it does have one, it disagrees with the
house style. It **inserts** a blank line after a local import and before a nested
``def``, unconditionally. So the rule is kept by not writing those: an import
belongs at module level, and a nested function usually wants to be a module-level
one.

That makes this test the enforcement, and the two situations it cannot be talked
out of are exactly the two it drove out of the codebase.
"""

import ast
import pathlib
import re

import pytest

SOURCE_DIRS = ("typing_validation", "test", "benchmark")

_FIELD = re.compile(r":(param|return|returns|rtype|type)\b")
"""
``:raises:`` is deliberately absent: autodoc renders it, and nothing in the
annotations says which exceptions a function raises, so it is the one field that
is neither duplicated nor contradicted by the type hints.
"""

ROOT = pathlib.Path(__file__).parent.parent


def _files() -> list[pathlib.Path]:
    return [
        path
        for name in SOURCE_DIRS
        for path in sorted((ROOT / name).glob("*.py"))
    ]


def _blocks(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[list[ast.stmt]]:
    """Every run of consecutive statements inside a function, nesting included."""
    found: list[list[ast.stmt]] = []
    for node in ast.walk(fn):
        if node is not fn and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            # A nested definition keeps its own conventions.
            continue
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if (
                isinstance(block, list)
                and block
                and isinstance(block[0], ast.stmt)
            ):
                found.append(block)
    return found


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_no_blank_lines_inside_function_bodies(path: pathlib.Path) -> None:
    source = path.read_text()
    lines = source.splitlines()
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for block in _blocks(node):
            for previous, following in zip(block, block[1:]):
                for line in range(previous.end_lineno or 0, following.lineno):
                    if lines[line].strip() == "":
                        offenders.append(
                            f"{path.name}:{line + 1} in {node.name}"
                        )
    assert not offenders, "blank lines inside function bodies: " + ", ".join(
        offenders
    )


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_no_param_or_return_fields_in_docstrings(path: pathlib.Path) -> None:
    """
    ``autodoc_typehints`` renders parameters and returns from the annotations, so
    a ``:param:`` or ``:return:`` field is either duplicated or contradicted —
    and the annotation is the one that cannot go stale.
    """
    offenders: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module),
        ):
            continue
        doc = ast.get_docstring(node)
        if doc is None:
            continue
        for line in doc.splitlines():
            # A field list starts a line. Prose that merely mentions ``:param:``
            # — as the docstring above does — is not one.
            match = _FIELD.match(line.strip())
            if match is not None:
                name = getattr(node, "name", path.name)
                offenders.append(f"{path.name}:{name} has '{match.group(0)}'")
    assert not offenders, "; ".join(offenders)
