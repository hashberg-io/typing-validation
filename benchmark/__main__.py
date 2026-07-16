# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Running the suite: ``python -m benchmark``.

The only entry point, and thin on purpose: parse the arguments, run the pipeline
once, render what it measured, and put the result where it was asked to go. The
same numbers reach the terminal and the file, because there is only one set of
them.

Units are **nanoseconds per call** — the number a user actually experiences —
and **per type-node visited**, for comparing across shapes. Neither is divided by
anything the caller does not control, which is where v1's ``ns/B`` went wrong: it
divided by ``sys.getsizeof``, so its figures moved with the magnitude of an
integer while the work stayed constant, and could not be compared across types at
all.

Results are printed and tracked over time rather than gated in CI: a hard
threshold on a noisy shared runner produces flakes and then gets disabled, which
is worse than not having it.
"""

import argparse
import pathlib
import sys
from typing import Any

from .tools.report import render
from .tools.suite import regressions, run

REPORT = pathlib.Path(__file__).parent / "REPORT.md"
"""Where the report lives, next to the suite that produced it."""


def _utf8(stream: Any, /) -> None:
    """
    Say what encoding the report is in, rather than inheriting one.

    The report is full of ``µs``, ``—`` and ``⚠``, and a Windows console is
    cp1252, which has none of them. Left alone, the suite runs for minutes and
    then dies on the last line, printing the report it spent that long
    measuring — and the same silence applies to the file, which is why writing
    it names its encoding too.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")


def _progress(line: str, /) -> None:
    # To stderr, so that `python -m benchmark > somewhere` is the report and
    # nothing else. The suite takes minutes, and silence for minutes is
    # indistinguishable from a hang.
    print(line, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The benchmark suite.")
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"write {REPORT.name} instead of printing the report",
    )
    parser.add_argument(
        "--filter", default="", help="only run cases whose name contains this"
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=2000,
        help="calls per timing round (default: 2000)",
    )
    parser.add_argument(
        "--no-peers",
        action="store_true",
        help="skip the ecosystem half, which needs `uv sync --group peers`",
    )
    parser.add_argument(
        "--no-extended",
        action="store_true",
        help="measure the peers on the flat corpus only",
    )
    args = parser.parse_args(argv)
    _utf8(sys.stdout)
    _utf8(sys.stderr)
    report = run(
        args.repeats,
        only=args.filter,
        with_peers=not args.no_peers,
        with_extended=not args.no_extended,
        progress=_progress,
    )
    text = render(report)
    if args.write:
        REPORT.write_text(text, encoding="utf-8")
        _progress(f"\nwrote {REPORT}")
    else:
        print(text)
    # The one number that may never regress, said out loud at the end rather
    # than left in a table for someone to find. It does not fail the run: the
    # suite is tracked over time rather than gated, and a threshold that fails
    # is a threshold that gets disabled.
    slower = regressions(report)
    if slower:
        _progress("REGRESSED AGAINST v1: " + ", ".join(slower))
    else:
        _progress("No regression against v1 on any comparable case.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
