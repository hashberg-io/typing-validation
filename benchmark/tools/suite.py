# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The pipeline: one run, one set of numbers, one report.

Everything is measured in a single pass, so that the figures printed to a
terminal and the figures committed to the repository are the same figures.
Measuring twice — once for the reader at a terminal and once for the file — puts
two implementations of one measurement in the tree with nothing comparing them,
and they drift silently, because nothing is watching. A benchmark that reports
differently depending on who is reading it is not a benchmark.

The two halves stay separate corpora to the end. The flat corpus is what the
mechanisms are measured on and what the regression check reads; the extended
corpus exists for the peer comparison, where a wider spread of type features is
the whole point. They are never merged into one table, because a baseline that
grows is not a baseline.
"""

from dataclasses import dataclass
from typing import Any, Callable, final

from .extended import extended_cases
from .cases import Case, cases
from .compare import Comparison, compare
from .contenders import Contender, contenders
from .environment import environment
from .measure import Result, measure
from .v1 import load_v1

__all__ = ("Corpus", "PeerRun", "Report", "regressions", "run")

FLAT = "flat"
"""The corpus the mechanisms are measured on, and the one that may not grow."""

EXTENDED = "extended"
"""The corpus the peers are measured on, where breadth is the point."""

_BLURB = {
    FLAT: (
        "Scalars, one-level collections, and one recursive alias. JSON-shaped, "
        "and deliberately small: this is the corpus the mechanisms are measured "
        "on and the one the regression check reads, so it is a baseline, and a "
        "baseline that grows is not one."
    ),
    EXTENDED: (
        "Eight type features — scalar, collection, nested, structured, union, "
        "recursive, generic, numpy — measured alone, then crossed in the pairs "
        "and triples that are inhabitable and that people actually write. Not "
        "all 127 subsets: most are uninhabitable (a scalar cannot be recursive) "
        "or absurd (a `Literal` inside a dtype)."
    ),
}


@final
@dataclass(frozen=True, slots=True)
class Corpus:
    """A named body of cases, and why it exists."""

    name: str
    """What to call it in the report."""

    blurb: str
    """What it covers, and what it is deliberately not."""

    cases: list[Case]
    """The cases themselves, already filtered."""


@final
@dataclass(frozen=True, slots=True)
class PeerRun:
    """Every library against every case of one corpus."""

    corpus: Corpus
    """Which cases were used."""

    results: dict[str, list[Comparison]]
    """What each library did, keyed by case name."""


@final
@dataclass(frozen=True, slots=True)
class Report:
    """Everything one run measured."""

    environment: dict[str, Any]
    """The machine, without which no figure here means anything."""

    repeats: int
    """
    Calls per timing round.

    Recorded for the same reason the machine is. It does not move a figure — each
    is the best of five rounds, divided by this — but it says how much of the
    noise was averaged out, and two reports taken at different counts are not
    equally trustworthy.
    """

    mechanisms: list[Result]
    """The three mechanisms and their two baselines, on the flat corpus."""

    contenders: list[Contender]
    """The peer libraries that were importable. Empty when the peers were
    skipped, or when none of them are installed."""

    peers: list[PeerRun]
    """One entry per corpus the peers were measured on."""

    v1: bool
    """Whether v1 could be loaded, so its absence reads as absence."""


def _select(corpus: list[Case], only: str, /) -> list[Case]:
    return [c for c in corpus if only in c.name]


def run(
    repeats: int,
    /,
    *,
    only: str = "",
    with_peers: bool = True,
    with_extended: bool = True,
    progress: Callable[[str], None] | None = None,
) -> Report:
    """
    Measure everything, once.

    ``progress`` is called with a line per case, because the suite takes minutes
    and silence for minutes is indistinguishable from a hang.
    """
    say = progress if progress is not None else _quiet
    v1 = load_v1()
    flat = Corpus(FLAT, _BLURB[FLAT], _select(cases(), only))
    say(f"mechanisms: {len(flat.cases)} cases")
    mechanisms = []
    for case in flat.cases:
        say(f"  {case.name}")
        mechanisms.append(measure(case, repeats, v1))
    libs = contenders() if with_peers else []
    corpora = [flat]
    if with_extended:
        corpora.append(
            Corpus(EXTENDED, _BLURB[EXTENDED], _select(extended_cases(), only))
        )
    runs: list[PeerRun] = []
    for corpus in corpora:
        # A corpus a filter has emptied is left out rather than reported empty:
        # a section of tables whose every cell says "not measured" reads like a
        # finding, and it is an argument to `--filter`.
        if not libs or not corpus.cases:
            continue
        say(
            f"peers on the {corpus.name} corpus: "
            f"{len(libs)} libraries, {len(corpus.cases)} cases"
        )
        results: dict[str, list[Comparison]] = {}
        for case in corpus.cases:
            say(f"  {case.name}")
            results[case.name] = [compare(case, lib, repeats) for lib in libs]
        runs.append(PeerRun(corpus, results))
    return Report(
        environment=environment(),
        repeats=repeats,
        mechanisms=mechanisms,
        contenders=libs,
        peers=runs,
        v1=v1 is not None,
    )


def _quiet(_: str, /) -> None:
    pass


def regressions(report: Report, /) -> list[str]:
    """
    The cases where ``validate`` is slower than v1.

    The number that matters most, and the reason the suite says something out
    loud at the end rather than leaving it in a table. ``validate`` is the
    function everybody calls and most people will only ever call: if the redesign
    buys two new mechanisms at the cost of the common path, it has failed
    regardless of what the other two achieve.
    """
    slower = []
    for result in report.mechanisms:
        ours = result.per_call.get("validate")
        theirs = result.per_call.get("v1")
        if ours is None or theirs is None:
            continue
        if theirs < ours:
            slower.append(result.case.name)
    return slower
