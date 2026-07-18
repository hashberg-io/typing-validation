# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Taking the measurements, separately from reporting them.

Split out because the numbers are now consumed twice — printed to a terminal and
written to a table in the repository — and a measurement that has to be taken
differently depending on who is reading it is not a measurement.
"""

import timeit
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable, final

from typing_validation import (
    clear_cache,
    compiled_validator,
    is_valid,
    validate,
    validator,
)

from .cases import Case

__all__ = ("Result", "measure")


@final
@dataclass(frozen=True, slots=True)
class Result:
    """Everything measured for one case, in nanoseconds unless stated."""

    case: Case
    """What was measured."""

    per_call: dict[str, float | None] = field(default_factory=dict)
    """Nanoseconds per call on a **valid** value, by mechanism."""

    per_call_invalid: dict[str, float | None] = field(default_factory=dict)
    """
    Nanoseconds per call on an **invalid** value, by mechanism.

    Measured because the design assumes failures are exceptional and so paying
    twice for one — once to fail, once to explain — is free. That is an
    assumption in a performance argument, which is exactly what a benchmark is
    for.
    """

    build: dict[str, float | None] = field(default_factory=dict)
    """Nanoseconds to analyse the type, for the mechanisms that analyse it."""


MECHANISMS = (
    "validate",
    "validator",
    "compiled_validator",
    "hand-written",
    "v1",
)
"""
The columns, in the order a reader meets them.

Three mechanisms and two baselines. The baselines are not choices — one is
aspirational and one is history — but they are what make the three mean anything:
hand-written is what the compiled path claims to reach, and v1 is the number that
may never regress.
"""


def _time(fn: Callable[[], Any], repeats: int, /) -> float:
    return min(timeit.repeat(fn, repeat=5, number=repeats)) / repeats * 1e9


def _cold(build: Callable[[], Any], /) -> Callable[[], Any]:
    """
    Build from an empty cache.

    Warm, this would measure a dictionary lookup: the second validator for a type
    reuses the first one's work, which is the point of interning and the opposite
    of what a construction cost means.
    """

    def run() -> Any:
        clear_cache()
        return build()

    return run


def _swallow(fn: Callable[[], Any], /) -> None:
    """Run something and discard its failure, to measure work not tracebacks."""
    try:
        fn()
    except Exception:
        pass


def measure(case: Case, repeats: int, v1: ModuleType | None, /) -> Result:
    """Every number for one case."""
    result = Result(case=case)
    n = max(50, repeats // max(1, case.nodes // 50))
    result.per_call["validate"] = _time(lambda: validate(case.valid, case.t), n)
    result.per_call_invalid["validate"] = _time(
        lambda: _swallow(lambda: validate(case.invalid, case.t)), n
    )
    result.build["validator"] = _time(
        _cold(lambda: validator(case.t)), max(20, n // 20)
    )
    check = validator(case.t)
    result.per_call["validator"] = _time(lambda: check(case.valid), n)
    result.per_call_invalid["validator"] = _time(
        lambda: _swallow(lambda: check(case.invalid)), n
    )
    result.build["compiled_validator"] = _time(
        _cold(lambda: compiled_validator(case.t)), max(20, n // 20)
    )
    compiled = compiled_validator(case.t)
    result.per_call["compiled_validator"] = _time(
        lambda: compiled(case.valid), n
    )
    result.per_call_invalid["compiled_validator"] = _time(
        lambda: _swallow(lambda: compiled(case.invalid)), n
    )
    if case.baseline is not None:
        hand = case.baseline
        result.per_call["hand-written"] = _time(lambda: hand(case.valid), n)
        # A hand-written check returns False and explains nothing, so its failure
        # figure is not comparable with the others and is not reported.
        result.per_call_invalid["hand-written"] = None
    else:
        result.per_call["hand-written"] = None
        result.per_call_invalid["hand-written"] = None
    result.per_call["v1"] = None
    result.per_call_invalid["v1"] = None
    if v1 is not None and case.v1_comparable:
        try:
            v1.validate(case.valid, case.t)
        except Exception:
            pass
        else:
            result.per_call["v1"] = _time(
                lambda: v1.validate(case.valid, case.t), n
            )
            result.per_call_invalid["v1"] = _time(
                lambda: _swallow(lambda: v1.validate(case.invalid, case.t)), n
            )
    return result


def break_even(
    result: Result, mechanism: str, against: str, /
) -> float | None | str:
    """
    How many values before the cheaper call has repaid the analysis.

    :obj:`None` when one side was not measured; ``"never"`` when the analysis
    buys nothing, which is a fact worth publishing rather than a gap.
    """
    build = result.build.get(mechanism)
    mine = result.per_call.get(mechanism)
    theirs = result.per_call.get(against)
    if build is None or mine is None or theirs is None:
        return None
    if theirs <= mine:
        return "never"
    return build / (theirs - mine)
