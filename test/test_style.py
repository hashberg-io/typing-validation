# SPDX-License-Identifier: LGPL-3.0-or-later

"""
House style that a formatter cannot enforce.

``black`` settles almost everything, but it has no opinion on blank lines
*within* a function body — and where it does have one, it disagrees with the
house style. It **inserts** one after a local import and around a nested ``def``,
unconditionally.

For local imports the rule wins, by not writing them: an import belongs at module
level, and hoisting them is what drove the last of them out.

For nested definitions it cannot, and should not. A closure factory has a nested
``def`` because that is what composing closures *is*, so banning the blank line
would ban the technique rather than tidy it. Those blanks are black's rather than
the author's, and are exempt — narrowly: the one before a nested definition and
the one after its body, and nothing else.
"""

import ast
import io
import pathlib
import re
import tokenize

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


def _string_lines(source: str) -> set[int]:
    """Lines occupied by a string literal, where a blank line is content."""
    inside: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.STRING:
            inside.update(range(token.start[0], token.end[0] + 1))
    return inside


def _function_lines(source: str) -> dict[int, str]:
    """Every line inside a function body, mapped to the function's name."""
    owner: dict[int, str] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = node.body[0].lineno
        for line in range(start, (node.end_lineno or start) + 1):
            owner.setdefault(line, node.name)
    return owner


def _blacks_own(source: str) -> set[int]:
    """
    Blank lines black puts around a nested ``def``, which it will not be argued
    out of.

    These are not the author's, and the rule is about the author's. A closure
    factory cannot exist without a nested ``def`` — that *is* what composing
    closures means — so demanding no blank line there would not tidy the module,
    it would ban the technique.

    Kept narrow deliberately: only the blank immediately before a nested
    definition, and the one immediately after its body. Every other blank line
    inside a function is still the author's, and still forbidden.
    """
    tree = ast.parse(source)
    forced: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        for inner in ast.walk(node):
            # Any definition nested anywhere inside — including under an `if`,
            # which is where a compositor puts them.
            if inner is node or not isinstance(
                inner, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            first = min(
                [inner.lineno] + [d.lineno for d in inner.decorator_list]
            )
            forced.add(first - 1)
            forced.add((inner.end_lineno or first) + 1)
    return forced


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_no_blank_lines_inside_function_bodies(path: pathlib.Path) -> None:
    source = path.read_text()
    lines = source.splitlines()
    in_string = _string_lines(source)
    forced = _blacks_own(source)
    owner = _function_lines(source)
    offenders = [
        f"{path.name}:{line} in {name}"
        for line, name in sorted(owner.items())
        if not lines[line - 1].strip()
        and line not in in_string
        and line not in forced
    ]
    assert not offenders, "blank lines inside function bodies: " + ", ".join(
        offenders
    )


_DEVELOPER_TALK = re.compile(
    r"\bv1\b|\bversion 1\b|\bv2\b|\b2\.[0-9]\b|eleven releases", re.IGNORECASE
)


@pytest.mark.parametrize(
    "path",
    [p for p in _files() if p.parent.name == "typing_validation"],
    ids=lambda p: p.name,
)
def test_docstrings_do_not_talk_about_other_releases(
    path: pathlib.Path,
) -> None:
    """
    A docstring is documentation for a user, who has never seen v1 and does not
    care what a later release will add.

    The test to apply: *is this useful to someone who has never seen v1?* If not
    it is developer context — real and worth keeping, but as an inline comment,
    which is read by the person it is for.
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
        found = _DEVELOPER_TALK.findall(doc)
        if found:
            name = getattr(node, "name", "<module>")
            offenders.append(
                f"{path.name}:{name} mentions {sorted(set(found))}"
            )
    assert not offenders, "; ".join(offenders)


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
