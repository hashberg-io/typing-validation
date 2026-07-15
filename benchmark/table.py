# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Rendering the measurements as a table meant to be read in the repository.

**Aligned in the source, not only when rendered.** A markdown table whose columns
line up only after a renderer has been at it is a table nobody reads in a diff,
and a diff is where this one will mostly be met.

One table per measured quantity, cases down the side and mechanisms across. A row
is then comparable: every cell in it is the same number about the same values,
which is what makes `compiled_validator` closing on hand-written — and failing to,
at a plugin — visible at a glance rather than derivable.
"""

from typing import Any

from .measure import MECHANISMS, Result, break_even

__all__ = ("render",)

_NOT_MEASURED = "—"
"""No such measurement exists: nobody wrote a hand-written check for this case."""

_UNSUPPORTED = "n/a"
"""
The mechanism cannot validate this type at all, which is a different fact.

v1 supports neither recursive aliases nor `Annotated`, and a single glyph for
*"not measured"* and *"cannot be measured"* would quietly merge a gap in the
suite with a gap in v1.
"""


def _escape(text: object, /) -> str:
    # A pipe in a case name ends the cell: `int | None` is a real type name.
    return str(text).replace("|", "\\|")


def _table(
    header: list[str], aligns: list[str], body: list[list[Any]], /
) -> str:
    rows = [[_escape(cell) for cell in row] for row in body]
    head = [_escape(cell) for cell in header]
    widths = [max(len(cell) for cell in col) for col in zip(*([head] + rows))]

    def line(cells: list[str]) -> str:
        return (
            "| "
            + " | ".join(
                cell.rjust(width) if align == ">" else cell.ljust(width)
                for cell, width, align in zip(cells, widths, aligns)
            )
            + " |"
        )

    rule = (
        "|"
        + "|".join(
            (
                (":" + "-" * (width + 1))
                if align == "<"
                else ("-" * (width + 1) + ":")
            )
            for width, align in zip(widths, aligns)
        )
        + "|"
    )
    return "\n".join([line(head), rule] + [line(row) for row in rows])


def _ns(value: float | None, /) -> str:
    if value is None:
        return _NOT_MEASURED
    if value < 1000:
        return f"{value:.0f}"
    if value < 1e6:
        return f"{value / 1000:.1f}k"
    return f"{value / 1e6:.2f}M"


def _cell(
    result: Result, mechanism: str, values: dict[str, float | None], /
) -> str:
    if values.get(mechanism) is not None:
        return _ns(values[mechanism])
    if mechanism == "v1" and not result.case.v1_comparable:
        return _UNSUPPORTED
    if mechanism == "v1" and result.case.v1_comparable:
        # Measured, and v1 refused the type.
        return _UNSUPPORTED
    return _NOT_MEASURED


def _per_call(results: list[Result], /) -> str:
    body = [
        [r.case.name, r.case.nodes]
        + [_cell(r, m, r.per_call) for m in MECHANISMS]
        for r in results
    ]
    return _table(
        ["Case", "nodes"] + list(MECHANISMS), ["<", ">"] + [">"] * 5, body
    )


def _per_node(results: list[Result], /) -> str:
    body = []
    for r in results:
        row: list[Any] = [r.case.name, r.case.nodes]
        for m in MECHANISMS:
            value = r.per_call.get(m)
            row.append(
                _cell(r, m, r.per_call)
                if value is None
                else f"{value / r.case.nodes:.1f}"
            )
        body.append(row)
    return _table(
        ["Case", "nodes"] + list(MECHANISMS), ["<", ">"] + [">"] * 5, body
    )


def _per_call_invalid(results: list[Result], /) -> str:
    body = [
        [r.case.name, r.case.nodes]
        + [_cell(r, m, r.per_call_invalid) for m in MECHANISMS]
        for r in results
    ]
    return _table(
        ["Case", "nodes"] + list(MECHANISMS), ["<", ">"] + [">"] * 5, body
    )


def _build(results: list[Result], /) -> str:
    body = [
        [
            r.case.name,
            _ns(r.build.get("validator")),
            _ns(r.build.get("compiled_validator")),
        ]
        for r in results
    ]
    return _table(
        ["Case", "validator", "compiled_validator"], ["<", ">", ">"], body
    )


def _break_even(results: list[Result], /) -> str:
    body = []
    for r in results:
        row = [r.case.name]
        for mechanism, against in (
            ("validator", "validate"),
            ("compiled_validator", "validate"),
            ("compiled_validator", "validator"),
        ):
            value = break_even(r, mechanism, against)
            if value is None:
                row.append(_NOT_MEASURED)
            elif isinstance(value, str):
                row.append(value)
            else:
                row.append(f"{value:.0f}")
        body.append(row)
    return _table(
        [
            "Case",
            "validator vs validate",
            "compiled vs validate",
            "compiled vs validator",
        ],
        ["<", ">", ">", ">"],
        body,
    )


def render(results: list[Result], environment: dict[str, Any], /) -> str:
    """The whole document."""
    parts = [
        "# Benchmark results",
        "",
        "Generated by `python -m benchmark --write`. Committed deliberately:",
        "a threshold on a shared runner produces flakes and then gets disabled,",
        "so these are tracked over time rather than gated, and the diff is the",
        "record.",
        "",
        "## Environment",
        "",
        "A figure without its context is unreadable six months later, and",
        "numbers from different machines must never be compared.",
        "",
    ]
    parts.append(
        _table(
            ["", ""],
            ["<", "<"],
            [[key, str(value)] for key, value in environment.items()],
        )
    )
    parts += [
        "",
        "## Reading these",
        "",
        f"- `{_NOT_MEASURED}` — not measured. Nobody wrote a hand-written check",
        "  for this case, which says nothing about the case.",
        f"- `{_UNSUPPORTED}` — the mechanism cannot validate this type at all.",
        "  v1 supports neither recursive aliases nor `Annotated`.",
        "- `never` — the analysis buys nothing here, so building a validator",
        "  cannot repay. A fact, not a gap: it is what a plugin and a recursive",
        "  alias both do, because each stops the unrolling.",
        "- **nodes** is how many type-nodes one validation visits, and is the",
        "  closest thing to a unit of work. Bytes are not: validating any `int`",
        "  is one `isinstance`, while its size ranges from 28 to 72 bytes.",
        "",
        "## Nanoseconds per call, valid value",
        "",
        "What a user actually experiences.",
        "",
        _per_call(results),
        "",
        "## Nanoseconds per type-node visited, valid value",
        "",
        "For comparing across shapes, which the per-call figure cannot do.",
        "",
        _per_node(results),
        "",
        "## Nanoseconds per call, invalid value",
        "",
        "The failure path pays for a **second traversal**: the validators fail",
        "hard and know only *that* they failed, so the explanation is built",
        "afterwards, by walking the value again. The design assumes failures are",
        "exceptional and so paying twice is free — an assumption in a",
        "performance argument, which is what a benchmark is for.",
        "",
        "A hand-written check is absent here rather than fast: it returns",
        "`False` and explains nothing, so its figure would not be comparable.",
        "",
        _per_call_invalid(results),
        "",
        "## Nanoseconds to build",
        "",
        "Measured from a cold cache. Warm, this would measure a dictionary",
        "lookup: the second validator for a type reuses the first one's work,",
        "which is the point of interning and the opposite of a construction",
        "cost. Only two mechanisms build anything.",
        "",
        _build(results),
        "",
        "## Break-even: values before building has repaid itself",
        "",
        "The only number that answers the question a user actually has — *which",
        "of these should I use?* — and it turns the choice from folklore into a",
        "lookup.",
        "",
        _break_even(results),
        "",
    ]
    return "\n".join(parts) + "\n"
