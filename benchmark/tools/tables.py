# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Markdown tables meant to be read in the repository.

**Aligned in the source, not only when rendered.** A markdown table whose columns
line up only after a renderer has been at it is a table nobody reads in a diff,
and a diff is where this one will mostly be met.

The primitives only. What goes into a table, and in what order, is
:mod:`benchmark.tools.report`'s business.
"""

from typing import Any

__all__ = ("NOT_MEASURED", "UNSUPPORTED", "escape", "ns", "table")

NOT_MEASURED = "—"
"""No such measurement exists: nobody wrote a hand-written check for this case."""

UNSUPPORTED = "n/a"
"""
The check cannot be made at all, which is a different fact.

A single glyph for *"not measured"* and *"cannot be measured"* would quietly
merge a gap in the suite with a gap in the thing measured.
"""


def escape(text: object, /) -> str:
    # A pipe in a case name ends the cell: `int | None` is a real type name.
    return str(text).replace("|", "\\|")


def ns(value: float | None, /) -> str:
    """
    A duration, scaled to the unit a reader can hold in their head.

    One formatter for every table in the report, because two would invite exactly
    the comparison the report spends its length refusing: figures formatted alike
    should be alike. The unit travels with the number rather than living in the
    header, so a cell lifted out of its table still says what it means.
    """
    if value is None:
        return NOT_MEASURED
    if value >= 1e6:
        return f"{value / 1e6:.2f} ms"
    if value >= 1e3:
        return f"{value / 1e3:.1f} µs"
    if value >= 10:
        return f"{value:.0f} ns"
    # Below ten, a whole number is mostly rounding. The per-node figures live
    # here, and they are the ones a reader compares across shapes.
    return f"{value:.1f} ns"


def table(
    header: list[str], aligns: list[str], body: list[list[Any]], /
) -> str:
    """One markdown table, padded so that its columns line up in the source."""
    rows = [[escape(cell) for cell in row] for row in body]
    head = [escape(cell) for cell in header]
    if not rows:
        rows = [[NOT_MEASURED] * len(head)]
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
