# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The report: everything one run measured, as one document.

One document, not one per question. A reader asking the obvious thing — *is this
library fast, and next to what?* — should not have to hold several files open and
trust that the numbers in them came from the same machine on the same afternoon.
Nothing but a single pass guarantees that they did.

The halves answer different questions and keep their own sections, which is not
the same as keeping their own files:

- **The mechanisms** ask whether three validators earn their complexity. The
  answer is a number, and one of them may never regress.
- **The ecosystem** asks where the library sits among its peers. The answer is
  mostly *not* a number — it is which libraries are even asking the same
  question.

Prose here is written unwrapped, one paragraph to a line, because the document is
Markdown and a hard wrap makes a diff noisy for no reader's benefit. The tables
are the opposite: padded to line up in the source, because a diff is where they
will mostly be met.
"""

import math
from typing import Any

from .compare import Comparison
from .contenders import Contender, Tier, Usage, audit
from .measure import MECHANISMS, Result, break_even
from .suite import PeerRun, Report
from .tables import NOT_MEASURED, UNSUPPORTED, ns, table

__all__ = ("render",)

_USAGE_BLURB = {
    Usage.AD_HOC: (
        "The type is passed per call and analysed per call. These race "
        "`validate`, which works the same way, and only these."
    ),
    Usage.PREPARED: (
        "The type is analysed once into a reusable callable. These race "
        "`validator` and `compiled_validator`, and only these. A library "
        "appears here only if it offers such an API; its absence is not a "
        "loss, it is a different surface."
    ),
}

_TIER_BLURB = {
    Tier.EXACT: (
        "Same question, same work: a verdict on the whole value, without "
        "building anything. Only these figures race `validate` fairly."
    ),
    Tier.REBUILDING: (
        "Same verdict once coercion is off, but they return a **new object**. "
        "The allocation cannot be disabled, so their figures carry an inherent "
        "handicap: read them as an upper bound on the cost of the question, "
        "never as a like-for-like loss."
    ),
    Tier.SAMPLING: (
        "**Not the same work.** They check O(1) items per container whatever "
        "its size, and so return `True` for values that are not of the type. "
        "Excluded from the race; timing them against a full check measures the "
        "corpus, not the library."
    ),
}


def _mechanism_cell(
    result: Result, mechanism: str, values: dict[str, float | None], /
) -> str:
    if values.get(mechanism) is not None:
        return ns(values[mechanism])
    if mechanism == "v1":
        # Measured and refused, or never comparable in the first place. Either
        # way v1 cannot validate this type, which is not the same fact as nobody
        # having written a check for it.
        return UNSUPPORTED
    return NOT_MEASURED


def _mechanism_table(
    results: list[Result], values: str, /, *, per_node: bool = False
) -> str:
    body = []
    for r in results:
        row: list[Any] = [r.case.name, r.case.nodes]
        measured: dict[str, float | None] = getattr(r, values)
        for mechanism in MECHANISMS:
            figure = measured.get(mechanism)
            if figure is not None and per_node:
                row.append(ns(figure / r.case.nodes))
            else:
                row.append(_mechanism_cell(r, mechanism, measured))
        body.append(row)
    return table(
        ["Case", "nodes"] + list(MECHANISMS), ["<", ">"] + [">"] * 5, body
    )


def _build_table(results: list[Result], /) -> str:
    body = [
        [
            r.case.name,
            ns(r.build.get("validator")),
            ns(r.build.get("compiled_validator")),
        ]
        for r in results
    ]
    return table(
        ["Case", "validator", "compiled_validator"], ["<", ">", ">"], body
    )


def _break_even_table(results: list[Result], /) -> str:
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
                row.append(NOT_MEASURED)
            elif isinstance(value, str):
                row.append(value)
            else:
                row.append(f"{value:.0f}")
        body.append(row)
    return table(
        [
            "Case",
            "validator vs validate",
            "compiled vs validate",
            "compiled vs validator",
        ],
        ["<", ">", ">", ">"],
        body,
    )


def _audit_table(libs: list[Contender], /) -> str:
    usage = {c.name: c.usage.value for c in libs}
    body = []
    for row in audit(libs):
        deep = {True: "yes", False: "**no**", None: NOT_MEASURED}[
            row.catches_deep
        ]
        coercible = {True: "yes", False: "**no**", None: NOT_MEASURED}[
            row.rejects_coercible
        ]
        body.append(
            [
                row.name,
                row.version,
                row.tier.value,
                usage.get(row.name, NOT_MEASURED),
                deep,
                coercible,
                row.note or NOT_MEASURED,
            ]
        )
    return table(
        [
            "library",
            "version",
            "tier",
            "usage",
            "catches a deep error",
            "rejects `['1','2']`",
            "how it was asked",
        ],
        ["<", "<", "<", "<", "<", "<", "<"],
        body,
    )


def _agreement_table(runs: list[PeerRun], libs: list[Contender], /) -> str:
    """
    How often each library returns this suite's verdict, counted twice over.

    Split on :attr:`Case.extension`, and never totalled. A library that does not
    implement ``__validate__`` or the NumPy plugin is not wrong about those
    cases, it is not playing: no peer claims either surface. Add them into one
    percentage and the number says only that typing-validation is the library
    that is typing-validation, while looking like a statement about the field —
    it puts the next-best library some thirty points behind us on a gap the
    corpus supplied rather than the measurement. The reach is real and is
    reported as reach; the agreement figure is the one a peer can argue with.
    """
    tally: dict[str, dict[str, list[int]]] = {}
    for run in runs:
        for name, comparisons in run.results.items():
            case = next(c.case for c in comparisons)
            group = "shared" if case.extension is None else "extension"
            for c in comparisons:
                slot = tally.setdefault(
                    c.contender.name,
                    {"shared": [0, 0, 0], "extension": [0, 0, 0]},
                )[group]
                if not c.supported:
                    slot[2] += 1
                elif c.agrees:
                    slot[0] += 1
                else:
                    slot[1] += 1
    body = []
    for lib in libs:
        counts = tally.get(lib.name)
        if counts is None:
            continue
        row = [lib.name]
        for group in ("shared", "extension"):
            ok, differs, cannot = counts[group]
            total = ok + differs + cannot
            pct = f"{100 * ok / total:.0f}%" if total else NOT_MEASURED
            row += [str(ok), str(differs), str(cannot), pct]
        body.append(row)
    return table(
        [
            "library",
            "agrees",
            "differs",
            "can't express",
            "% shared",
            "agrees",
            "differs",
            "can't express",
            "% extensions",
        ],
        ["<"] + [">"] * 8,
        body,
    )


_REFERENCE = {
    Usage.AD_HOC: ("typing-validation (validate)",),
    Usage.PREPARED: (
        "typing-validation (validator)",
        "typing-validation (compiled)",
    ),
}
"""
Which of our mechanisms a peer's figure is measured against.

By usage, because that is the axis no caveat repairs: a prepared validator raced
against a function that re-analyses the type per call measures the API, not the
library.
"""


def _records_table(runs: list[PeerRun], libs: list[Contender], /) -> str:
    """
    Win/loss and geometric mean against the mechanism a peer actually races.

    Restricted to cases where the peer agreed and both sides were measured: a
    wrong answer has no time, and a case a peer cannot express is not a case it
    lost. The record therefore comes from a different subset for every peer, and
    the count is printed so that the geomeans are not silently compared with each
    other.
    """
    ours: dict[str, dict[str, float]] = {}
    theirs: dict[str, dict[str, tuple[float, bool]]] = {}
    for run in runs:
        for name, comparisons in run.results.items():
            for c in comparisons:
                if c.per_call is None or not c.supported:
                    continue
                if c.contender.name.startswith("typing-validation"):
                    ours.setdefault(c.contender.name, {})[name] = c.per_call
                else:
                    theirs.setdefault(c.contender.name, {})[name] = (
                        c.per_call,
                        bool(c.agrees),
                    )
    body = []
    for lib in libs:
        if lib.name.startswith("typing-validation"):
            continue
        got = theirs.get(lib.name)
        if not got:
            continue
        for reference in _REFERENCE[lib.usage]:
            mine = ours.get(reference)
            if not mine:
                continue
            wins = losses = 0
            ratios = []
            for case, (figure, agrees) in got.items():
                if not agrees or case not in mine:
                    continue
                ratio = figure / mine[case]
                ratios.append(ratio)
                if ratio >= 1.0:
                    wins += 1
                else:
                    losses += 1
            if not ratios:
                continue
            geo = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
            # A win and a loss are different directions, so each is reported
            # only if it happened. Taking 1/min() unconditionally invented a
            # "worst loss" for a peer that lost nothing, and printed it beside
            # the 0L that contradicted it.
            won = [r for r in ratios if r >= 1.0]
            lost = [r for r in ratios if r < 1.0]
            body.append(
                [
                    lib.name,
                    reference.replace("typing-validation ", ""),
                    lib.tier.value,
                    f"{wins}W–{losses}L",
                    f"{len(ratios)}",
                    f"{geo:.2f}×",
                    f"{max(won):.1f}×" if won else NOT_MEASURED,
                    f"{1 / min(lost):.1f}×" if lost else NOT_MEASURED,
                ]
            )
    return table(
        [
            "library",
            "raced against",
            "tier",
            "record",
            "cases",
            "geomean",
            "best win",
            "worst loss",
        ],
        ["<", "<", "<", ">", ">", ">", ">", ">"],
        body,
    )


def _peer_cell(c: Comparison, /) -> str:
    if not c.supported:
        return UNSUPPORTED
    if c.agrees is False:
        return f"{ns(c.per_call)} ⚠"
    return ns(c.per_call)


def _peer_table(
    run: PeerRun, libs: list[Contender], tier: Tier, usage: Usage, /
) -> str:
    cols = [c for c in libs if c.tier is tier and c.usage is usage]
    body = []
    for name, comparisons in run.results.items():
        by_name = {c.contender.name: c for c in comparisons}
        row = [name]
        for col in cols:
            found = by_name.get(col.name)
            row.append(UNSUPPORTED if found is None else _peer_cell(found))
        body.append(row)
    return table(
        ["Case"] + [c.name for c in cols], ["<"] + [">"] * len(cols), body
    )


def _disagreements(runs: list[PeerRun], /) -> str:
    body = []
    for run in runs:
        for name, comparisons in run.results.items():
            for c in comparisons:
                if c.supported and c.agrees is False:
                    body.append(
                        [run.corpus.name, name, c.contender.name, c.detail]
                    )
                elif not c.supported and c.detail:
                    body.append(
                        [
                            run.corpus.name,
                            name,
                            c.contender.name,
                            f"unsupported: {c.detail}",
                        ]
                    )
    if not body:
        return "*None: every library agreed on every case it supported.*"
    return table(
        ["corpus", "case", "library", "what it did"], ["<", "<", "<", "<"], body
    )


def _mechanisms_part(report: Report, /) -> list[str]:
    results = report.mechanisms
    return [
        "## The three mechanisms",
        "",
        "Measured on the flat corpus, against two baselines. The baselines are not choices — one is aspirational and one is history — but they are what make the three mean anything: `hand-written` is what the compiled path claims to reach, and `v1` is the number that may never regress.",
        "",
        "### Per call, valid value",
        "",
        "What a user actually experiences.",
        "",
        _mechanism_table(results, "per_call"),
        "",
        "### Per type-node visited, valid value",
        "",
        "For comparing across shapes, which the per-call figure cannot do.",
        "",
        _mechanism_table(results, "per_call", per_node=True),
        "",
        "### Per call, invalid value",
        "",
        "The failure path pays for a **second traversal**: the validators fail hard and know only *that* they failed, so the explanation is built afterwards, by walking the value again. The design assumes failures are exceptional and so paying twice is free — an assumption in a performance argument, which is what a benchmark is for.",
        "",
        "A hand-written check is absent here rather than fast: it returns `False` and explains nothing, so its figure would not be comparable.",
        "",
        _mechanism_table(results, "per_call_invalid"),
        "",
        "### Time to build",
        "",
        "Measured from a cold cache. Warm, this would measure a dictionary lookup: the second validator for a type reuses the first one's work, which is the point of interning and the opposite of a construction cost. Only two mechanisms build anything.",
        "",
        _build_table(results),
        "",
        "### Break-even: values before building has repaid itself",
        "",
        "The only number that answers the question a user actually has — *which of these should I use?* — and it turns the choice from folklore into a lookup.",
        "",
        _break_even_table(results),
        "",
    ]


def _ecosystem_part(report: Report, /) -> list[str]:
    out = [
        "## The ecosystem",
        "",
        "Runtime type-checking is not one job done at different speeds. It is three jobs, and **most of the fast numbers in this ecosystem are fast because they answer a smaller question.** The libraries below are grouped by the question they answer, established by probe rather than by reputation. Timings within a group are comparable; timings across groups are not.",
        "",
    ]
    if not report.contenders:
        out += [
            "*Not measured: no peer library was importable. Install them with* `uv sync --group peers`*.*",
            "",
        ]
        return out
    out += [
        "### Tiers, established by probe",
        "",
        "Two probes place every library. A 1000-element list whose **last** item is wrong separates checking from sampling — anything answering `True` did not look. A list of numeric strings against `list[int]` separates checking from coercing. The classification is re-derived on every run, so it can be checked rather than believed.",
        "",
        _audit_table(report.contenders),
        "",
        "### Agreement",
        "",
        "How often each library returns this suite's verdict on both values of a case. **Counted twice over, and never added up.** The left half is the *shared surface* — the type forms the whole field claims to support. The right half is this library's own extensions: `__validate__`, which checks a generic's arguments, and the NumPy plugin. No peer implements either, so a library is not *wrong* about those cases, it is not playing; counting them into one percentage produces a figure that says typing-validation is the only library that is typing-validation.",
        "",
        "The column is called *agrees*, not *correct*, on purpose. On the shared surface this suite's verdict and correctness are the same thing, and where they might not be, the disagreement is itemised below and the reader can judge. Off it, a library that coerces or samples is answering a question it documents and we are not.",
        "",
        _agreement_table(report.peers, report.contenders),
        "",
        "### Records",
        "",
        "Each peer against the mechanism it actually races — ad-hoc against `validate`, prepared against `validator` and `compiled_validator` — over both corpora. A ratio above 1.0 means we are faster.",
        "",
        "**The `cases` column is why these geomeans must not be compared with each other.** A wrong answer has no time and a type a library cannot express is not a case it lost, so both are dropped, and every peer's record is therefore drawn from a different subset. A peer that can express only the easy third of the corpus can post a flattering number against us, or a damning one, and neither would mean what it looks like.",
        "",
        _records_table(report.peers, report.contenders),
        "",
    ]
    for run in report.peers:
        out += [
            f"### The {run.corpus.name} corpus",
            "",
            run.corpus.blurb,
            "",
            "⚠ marks a library that gave a different verdict on that case; the disagreements are itemised below. A faster wrong answer is not faster.",
            "",
        ]
        # Usage first, then tier, and never one table spanning both. Racing a
        # prepared validator against a function that re-analyses the type per
        # call measures the API that was chosen, not the library — and unlike
        # the tier handicap, no caveat repairs it, because the reader compares
        # the columns that are in front of them. Group by tier alone and
        # `compiled_validator` lands beside trycast under a heading promising a
        # fair race.
        for usage in (Usage.AD_HOC, Usage.PREPARED):
            if not any(c.usage is usage for c in report.contenders):
                continue
            out += [
                f"#### {usage.value.capitalize()}",
                "",
                _USAGE_BLURB[usage],
                "",
            ]
            for tier in (Tier.EXACT, Tier.REBUILDING, Tier.SAMPLING):
                if not any(
                    c.tier is tier and c.usage is usage
                    for c in report.contenders
                ):
                    continue
                out += [
                    f"##### {usage.value.capitalize()}, {tier.value}",
                    "",
                    _TIER_BLURB[tier],
                    "",
                    _peer_table(run, report.contenders, tier, usage),
                    "",
                ]
    out += [
        "### Disagreements",
        "",
        "Where a library supported a case but answered differently, or could not express the type. These are not benchmark noise: they are the part of a comparison a timing table cannot show.",
        "",
        _disagreements(report.peers),
        "",
    ]
    return out


def render(report: Report, /) -> str:
    """
    The whole document.

    The v1 regression verdict is deliberately not here, only the `validate` and
    `v1` columns it is computed from. The check is an unguarded ``<`` on two
    measured figures, and at least one case — ``NamedTuple`` — sits close enough
    to parity that the answer changes between runs of the same command. Printing
    that is honest; committing it would put a coin-flip in the diff and teach a
    reader to ignore the line that matters most.
    """
    out = [
        "# Benchmark report",
        "",
        "Generated by `python -m benchmark --write`. Committed deliberately: a threshold on a shared runner produces flakes and then gets disabled, so these are tracked over time rather than gated, and the diff is the record.",
        "",
        "The synthesis a reader should start from is [`PEER-COMPARISON.md`](PEER-COMPARISON.md), which is written rather than generated. This file is the authority for the numbers in it.",
        "",
        "## Environment",
        "",
        "A figure without its context is unreadable six months later, and numbers from different machines must never be compared.",
        "",
        table(
            ["", ""],
            ["<", "<"],
            [[key, str(value)] for key, value in report.environment.items()]
            + [["repeats", str(report.repeats)]],
        ),
        "",
        "## Reading these",
        "",
        f"- `{NOT_MEASURED}` — not measured. Nobody wrote a hand-written check for this case, which says nothing about the case.",
        f"- `{UNSUPPORTED}` — the type cannot be validated at all here, so there is nothing to measure.",
        "- `never` — the analysis buys nothing here, so building a validator cannot repay. A fact, not a gap: it is what a plugin and a recursive alias both do, because each stops the unrolling.",
        "- **nodes** is how many type-nodes one validation visits, and is the closest thing to a unit of work. Bytes are not: validating any `int` is one `isinstance`, while its size ranges from 28 to 72 bytes.",
        "",
    ]
    if not report.v1:
        out += [
            "*v1 could not be loaded, so its column is empty throughout and this run says nothing about the one figure that may never regress.*",
            "",
        ]
    out += _mechanisms_part(report)
    out += _ecosystem_part(report)
    return "\n".join(out) + "\n"
