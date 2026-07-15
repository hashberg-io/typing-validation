# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Running the suite: ``python -m benchmark``.

Units are **nanoseconds per call** — the number a user actually experiences —
and **nanoseconds per type-node visited**, for comparing across shapes. Neither
is divided by anything the caller does not control, which is where v1's ``ns/B``
went wrong: it divided by ``sys.getsizeof``, so its figures moved with the
magnitude of an integer while the work stayed constant, and could not be compared
across types at all.

Results are printed and tracked over time rather than gated in CI: a hard
threshold on a noisy shared runner produces flakes and then gets disabled, which
is worse than not having it.
"""

import argparse
import timeit
from typing import Any, Callable

from typing_validation import is_valid, validate

from .cases import Case, cases
from .environment import describe, environment
from .v1 import load_v1


def _time(fn: Callable[[], Any], repeats: int, /) -> float:
    """Nanoseconds per call, taking the best of several rounds."""
    timer = timeit.Timer(fn)
    rounds = 5
    best = min(timer.repeat(repeat=rounds, number=repeats))
    return best / repeats * 1e9


def _guard(fn: Callable[[], Any]) -> Callable[[], Any]:
    """Swallow the failure, so the failure path measures work and not a traceback."""

    def run() -> Any:
        try:
            return fn()
        except Exception:
            return None

    return run


def _row(name: str, value: float | None, per_node: float | None = None) -> str:
    if value is None:
        return f"    {name:34} {'n/a':>12}"
    cell = f"{value:>9.1f} ns"
    if per_node is not None:
        cell += f"  {per_node:>7.2f} ns/node"
    return f"    {name:34} {cell}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repeats",
        type=int,
        default=2000,
        help="calls per timing round (default: 2000)",
    )
    parser.add_argument(
        "--filter", default="", help="only run cases whose name contains this"
    )
    args = parser.parse_args()

    env = environment()
    print("Environment")
    print(describe(env))
    v1 = load_v1()
    print(f"\n  v1 for comparison: {getattr(v1, '__version__', 'unavailable')}")
    print(
        "\nns/call is what a user experiences; ns/node compares across shapes."
    )

    regressions: list[str] = []
    selected = [c for c in cases() if args.filter in c.name]
    for case in selected:
        print(f"\n  {case.name}  ({case.nodes} nodes)")
        n = case.repeats if hasattr(case, "repeats") else args.repeats
        n = max(50, n // max(1, case.nodes // 50))

        ours = _time(lambda: validate(case.valid, case.t), n)
        print(_row("validate (valid)", ours, ours / case.nodes))

        ours_bad = _time(_guard(lambda: validate(case.invalid, case.t)), n)
        # The failure path pays for a second traversal, on the assumption that
        # failures are exceptional so paying twice is free. An assumption in a
        # performance argument is exactly what a benchmark is for.
        print(_row("validate (invalid, + diagnose)", ours_bad))

        is_valid_bad = _time(lambda: is_valid(case.invalid, case.t), n)
        print(_row("is_valid (invalid, no diagnose)", is_valid_bad))

        if case.baseline is not None:
            hand = _time(lambda: case.baseline(case.valid), n)  # type: ignore[misc]
            print(_row("hand-written", hand, hand / case.nodes))
            print(
                f"    {'-> validate is':34} {ours / hand:>9.1f}x hand-written"
            )

        if v1 is not None and case.v1_comparable:
            try:
                v1.validate(case.valid, case.t)
            except Exception:
                print(_row("v1 (unsupported)", None))
                continue
            theirs = _time(lambda: v1.validate(case.valid, case.t), n)
            print(_row("v1 validate (valid)", theirs, theirs / case.nodes))
            ratio = theirs / ours
            verdict = f"{ratio:.2f}x v1"
            if ratio < 1.0:
                verdict += "  <-- SLOWER THAN v1"
                regressions.append(case.name)
            print(f"    {'-> validate is':34} {verdict:>9}")

    print("\n" + "=" * 66)
    if regressions:
        # The number that matters most. validate is the function everybody calls
        # and most people will only ever call: if the redesign buys two new
        # mechanisms at the cost of the common path, it has failed regardless of
        # what the other two achieve.
        print("REGRESSED AGAINST v1: " + ", ".join(regressions))
    else:
        print("No regression against v1 on any comparable case.")


if __name__ == "__main__":
    main()
