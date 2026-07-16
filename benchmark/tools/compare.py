# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Measuring the other libraries on this suite's corpus.

Kept apart from :mod:`benchmark.tools.measure` on purpose. That module measures the
three mechanisms against two baselines that are *known to agree* on every case,
so it can time first and explain later. Nothing here may assume agreement: a peer
either does not support a type form, or supports it and answers differently, and
both are results in their own right.

So every figure is gated on two questions asked before the clock starts:

1. **Does it support this type at all?** A library that raises on ``TypedDict``
   has no number, and an empty cell is the finding.
2. **Does it give the same verdict?** Both values, valid and invalid. A library
   that disagrees is timed anyway --- but the disagreement travels with the
   figure, because a faster wrong answer is not faster.

Whichever way those go, the case is never silently dropped.
"""

import timeit
from dataclasses import dataclass, field
from typing import Any, final

from .cases import Case
from .contenders import Contender, Tier

__all__ = ("Comparison", "compare")


@final
@dataclass(frozen=True, slots=True)
class Comparison:
    """What one library did with one case."""

    case: Case
    contender: Contender

    supported: bool = True
    """Whether the library could express the type at all."""

    agrees: bool | None = None
    """
    Whether it gave this suite's verdict on **both** values.

    :obj:`None` when unsupported. :obj:`False` is not an error and not a reason
    to withhold the timing --- it is the most interesting thing a peer benchmark
    can find, and it is reported next to the number it qualifies.
    """

    per_call: float | None = None
    """Nanoseconds per call on the valid value."""

    per_call_invalid: float | None = None
    """Nanoseconds per call on the invalid value."""

    build: float | None = None
    """Nanoseconds to analyse the type, where there is a build step."""

    detail: str = ""
    """Why it is unsupported, or how it disagrees."""


def _time(fn: Any, repeats: int, /) -> float:
    return min(timeit.repeat(fn, repeat=5, number=repeats)) / repeats * 1e9


def _verdicts(
    contender: Contender, case: Case, /
) -> tuple[bool | None, bool | None, str]:
    """The library's answer on both values, or why it has none."""
    try:
        good = contender.check(case.valid, case.t)
    except Exception as e:
        return None, None, f"raised on valid: {type(e).__name__}"
    try:
        bad = contender.check(case.invalid, case.t)
    except Exception as e:
        return bool(good), None, f"raised on invalid: {type(e).__name__}"
    return bool(good), bool(bad), ""


def compare(case: Case, contender: Contender, repeats: int, /) -> Comparison:
    """
    Every number for one library on one case, with support settled first.

    ``repeats`` is scaled down for heavy cases the same way :func:`measure.measure`
    scales it, so a thousand-element list does not dominate the wall clock.
    """
    n = max(50, repeats // max(1, case.nodes // 50))
    good, bad, why = _verdicts(contender, case)
    if good is None:
        return Comparison(
            case, contender, supported=False, agrees=None, detail=why
        )
    if bad is None:
        return Comparison(
            case, contender, supported=False, agrees=None, detail=why
        )
    # This suite's cases are built so that `valid` validates and `invalid` does
    # not. Anything else is a disagreement, and it is recorded rather than
    # smoothed over.
    agrees = bool(good) and not bool(bad)
    detail = ""
    if not agrees:
        if good and bad:
            detail = "accepts the invalid value"
        elif not good and not bad:
            detail = "rejects the valid value"
        else:
            detail = "inverted verdict"
    build_ns: float | None = None
    if contender.build is not None:
        try:
            prepared = contender.build(case.t)
            build = contender.build
            build_ns = _time(lambda: build(case.t), max(20, n // 20))
        except Exception as e:
            return Comparison(
                case,
                contender,
                supported=False,
                detail=f"build raised: {type(e).__name__}",
            )
        # The prepared callable is exercised before it is timed. `_verdicts`
        # above went through `check`, which for some libraries is a *different*
        # entry point: beartype's `TypeHint` rejects six type forms that
        # `is_bearable` accepts, and typedload's `Loader` trips an internal
        # assert on NamedTuple. Both are results about the prepared API, and
        # timeit surfaces them as a bare traceback from inside the timing loop.
        try:
            prepared(case.valid)
        except Exception as e:
            return Comparison(
                case,
                contender,
                supported=False,
                detail=f"prepared call raised: {type(e).__name__}",
            )
        call_valid = _time(lambda: prepared(case.valid), n)
        call_invalid = _time(lambda: _swallow(prepared, case.invalid), n)
    else:
        call_valid = _time(lambda: contender.check(case.valid, case.t), n)
        call_invalid = _time(
            lambda: _swallow_check(contender, case.invalid, case.t), n
        )
    return Comparison(
        case,
        contender,
        supported=True,
        agrees=agrees,
        per_call=call_valid,
        per_call_invalid=call_invalid,
        build=build_ns,
        detail=detail,
    )


def _swallow(fn: Any, val: Any, /) -> None:
    try:
        fn(val)
    except Exception:
        pass


def _swallow_check(contender: Contender, val: Any, t: Any, /) -> None:
    try:
        contender.check(val, t)
    except Exception:
        pass


def fastest_exact(comparisons: list[Comparison], /) -> tuple[str, float] | None:
    """
    The best :attr:`Tier.EXACT` figure among libraries that agreed.

    Restricted to that tier because a race is only a race between libraries doing
    the same work, and to agreeing libraries because a wrong answer has no time.
    """
    best: tuple[str, float] | None = None
    for c in comparisons:
        if c.contender.tier is not Tier.EXACT or not c.agrees:
            continue
        if c.per_call is None:
            continue
        if best is None or c.per_call < best[1]:
            best = (c.contender.name, c.per_call)
    return best
