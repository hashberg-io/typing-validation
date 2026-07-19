# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Whether a persistent cache for the compiled path could earn its risk.

``python -m benchmark.marshalling``

Exploratory. This answers one question and is not part of the report: **how much
of ``compiled_validator``'s construction could a marshalled artifact actually
skip**, and what would the load path have to pay to be safe?

The design record (DESIGN.md §12) defers marshalling behind an unsolved staleness
problem, and reasons about it as though the prize were the whole construction
cost. It is not. Construction has four phases and marshalling can only skip two
of them:

======================  ==========================================
``node_for(t)``         builds the node graph — **paid either way**
``_emit(node)``         generates source and populates globals
``compile(source)``     source to code object
``exec(code, globals)`` code object to callable — **paid either way**
======================  ==========================================

``exec`` is unavoidable: a code object is not a function until it is bound to
globals. ``node_for`` is unavoidable for two separate reasons, and either alone
is sufficient. First, a load that verifies the artifact is not stale has to
rebuild what the emitter read in order to compare it, and the node graph *is*
what the emitter read. Second, and independently of any verification, the emitted
globals can contain composed runners — a nested plugin puts one there — and
rebuilding those needs the graph anyway.

So the honest ceiling on the saving is ``emit + compile``, and the honest floor on
the cost is ``node + unmarshal + recipe + exec``. This measures all six against
the same corpus the report uses, and prints the difference.

The recipe is the mapping from generated names back to the objects the code
loads. It is measured rather than assumed, because it is the part a design would
have to invent: globals hold classes, tuples of classes, an internal sentinel and
composed runners, and only the first three could be written down.
"""

import argparse
import dataclasses
import importlib
import json
import marshal
import pathlib
import subprocess
import sys
import time
import types
from typing import Any, Callable

import typing_validation.emission as emission
from typing_validation import clear_cache, compiled_validator, validator
from typing_validation.composition import runner_for
from typing_validation.emission import (
    _INLINE_BUDGET,
    _Emission,
    _emit,
    _is_pure_call_out,
    _lines,
)
from typing_validation.nodes import TypeNode, node_for

from .tools.cases import cases
from .tools.measure import _time

FINDING = pathlib.Path(__file__).parent / "MARSHALLING.md"
"""Where the measurement lands, next to the probe that produced it."""

Recipe = list[tuple[str, str, Any]]
"""
A rebuildable description of one emitted function's globals.

Each entry is a name, a kind, and whatever that kind needs to resolve: a
``module:qualname`` pair for a class, a list of them for a tuple of classes, the
node to recompose for a runner, and nothing for the sentinel.
"""


@dataclasses.dataclass(frozen=True, slots=True)
class Probe:
    """Every number for one case."""

    name: str
    """What the report calls this case."""

    compiles: bool
    """
    Whether anything is compiled at all.

    ``compiled_validator`` hands back ``validator(t)`` when there is nothing to
    unroll, and then there is no code object and nothing to marshal. Such a case
    is not a marshalling failure, it is a case marshalling does not apply to, and
    folding the two together would flatter the result.
    """

    node_ns: float = 0.0
    """Cold ``node_for(t)`` — building the node graph."""

    decide_ns: float = 0.0
    """
    ``_is_pure_call_out(node)`` — deciding whether to compile at all.

    A fifth phase, and one the first draft of this probe missed: it showed up as
    a fifth of the build unaccounted for in ``sum/build``. It emits the whole
    body twice to compare against a call-out, so it is not cheap. A load skips
    it outright — the artifact's existence has already settled the question.
    """

    emit_ns: float = 0.0
    """``_emit(node)`` on a warm graph — source generation and globals."""

    compile_ns: float = 0.0
    """``compile(source)`` — source text to code object."""

    exec_ns: float = 0.0
    """``exec(code, globals)`` — code object to callable."""

    build_ns: float = 0.0
    """Cold ``compiled_validator(t)``, as the report measures it."""

    composed_ns: float = 0.0
    """
    Cold ``validator(t)`` — the yardstick that decides this.

    Marshalling's claim can only be *compiled's run speed at composed's build
    cost*. So the number to beat is not the compiled build it improves on, it is
    the composed build a caller could already have had for free. A load path
    slower than this one is asking for a persistent cache to reach a place
    ``validator`` already reaches without one.
    """

    dumps_ns: float = 0.0
    """``marshal.dumps`` of the code object, paid once when writing."""

    loads_ns: float = 0.0
    """``marshal.loads`` of the code object, paid on every load."""

    recipe_ns: float = 0.0
    """Rebuilding the globals from the recipe, paid on every load."""

    blob_bytes: int = 0
    """Size of the marshalled code object."""

    classes: int = 0
    """Globals resolvable by ``module:qualname``."""

    runners: int = 0
    """Globals that are composed runners, and so need the node graph."""

    others: int = 0
    """Globals that are neither — today, the internal sentinel."""

    unresolvable: int = 0
    """
    Class references that do not round-trip through ``module:qualname``.

    Each one is a class a real implementation could not persist a reference to,
    and so a type it would have to refuse to cache.
    """

    @property
    def saved_ns(self) -> float:
        """The ceiling on what marshalling could skip."""
        return self.decide_ns + self.emit_ns + self.compile_ns

    @property
    def load_ns(self) -> float:
        """What a safe load path would pay instead."""
        return self.node_ns + self.loads_ns + self.recipe_ns + self.exec_ns

    @property
    def net_ns(self) -> float:
        """Saving over a cold build. Negative means marshalling costs more."""
        return self.build_ns - self.load_ns

    @property
    def share(self) -> float:
        """Net saving as a share of the cold build."""
        return self.net_ns / self.build_ns if self.build_ns else 0.0

    @property
    def phases_ns(self) -> float:
        """
        The four phases added up, which should approximate the cold build.

        Printed rather than trusted. The phases are timed separately and the
        build is timed whole, so if they disagree by much then something moved
        between the two measurements and none of the row means anything. This
        column is how a reader checks that without rerunning it.
        """
        return (
            self.node_ns
            + self.decide_ns
            + self.emit_ns
            + self.compile_ns
            + self.exec_ns
        )

    def as_dict(self) -> dict[str, Any]:
        """Flat form, for handing back from a subprocess."""
        return dataclasses.asdict(self)


def _call_out_nodes(node: TypeNode, /) -> list[TypeNode]:
    """
    The nodes the emitter would hand to the composed validator.

    Recovered by running the emitter with its call-out hook recorded, because
    ``_Emission`` stores the runner a call-out produced but not the node it came
    from. A real implementation would record the provenance as it emitted; this
    is a probe, so it re-derives it.
    """
    seen: list[TypeNode] = []
    original = emission._call_out

    def recording(n: TypeNode, var: str, out: _Emission, /) -> list[str]:
        seen.append(n)
        return original(n, var, out)

    emission._call_out = recording
    try:
        _lines(node, "_v", _Emission(), depth=0, budget=_INLINE_BUDGET)
    finally:
        emission._call_out = original
    return seen


def _recipe(out: _Emission, call_outs: list[TypeNode], /) -> Recipe:
    """
    Describe the emitted globals well enough to rebuild them.

    This is the artifact's second half, and the reason marshalling is not simply
    ``marshal.dumps``: a type can never be a code constant, so every class the
    check names is a global the loader has to put back.
    """
    recipe: Recipe = []
    pending = list(call_outs)
    for name, value in out.globals.items():
        if isinstance(value, type):
            recipe.append((name, "class", _reference(value)))
        elif isinstance(value, tuple) and all(
            isinstance(v, type) for v in value
        ):
            recipe.append((name, "tuple", [_reference(v) for v in value]))
        elif callable(value) and pending:
            recipe.append((name, "runner", pending.pop(0)))
        else:
            recipe.append((name, "other", value))
    return recipe


def _rebuild(recipe: Recipe, /) -> dict[str, Any]:
    """Resolve a recipe back into a globals dictionary, as a loader would."""
    built: dict[str, Any] = {}
    for name, kind, payload in recipe:
        if kind == "class":
            module, qualname, _ = payload
            built[name] = _resolve(module, qualname)
        elif kind == "tuple":
            built[name] = tuple(_resolve(m, q) for m, q, _ in payload)
        elif kind == "runner":
            built[name] = runner_for(payload)
        else:
            built[name] = payload
    return built


def _resolve(module: str, qualname: str, /) -> Any:
    """
    Follow a ``module:qualname`` reference, as the loader would have to.

    Falls back to :mod:`types` because the reference a class reports is not
    always one that resolves: ``type(None)`` says its module is ``builtins``,
    and ``builtins.NoneType`` does not exist. See :func:`_reference`.
    """
    try:
        obj: Any = importlib.import_module(module)
        for part in qualname.split("."):
            obj = getattr(obj, part)
        return obj
    except ImportError, AttributeError:
        return getattr(types, qualname)


def _reference(cls: type, /) -> tuple[str, str, bool]:
    """
    A class's ``module:qualname``, and whether it actually round-trips.

    Worth counting rather than assuming. A recipe is only sound if the reference
    it writes down resolves back to the *same object*, and three kinds of class
    break that: ones whose module lies (``type(None)``), ones defined inside a
    function, and ones synthesised at runtime. A real implementation has to
    refuse to cache those rather than persist a reference it cannot follow.
    """
    module, qualname = cls.__module__, cls.__qualname__
    try:
        return module, qualname, _resolve(module, qualname) is cls
    except Exception:
        return module, qualname, False


def _counts(recipe: Recipe, /) -> tuple[int, int, int, int]:
    """How many globals of each kind, for the shape of the recipe problem."""
    classes = sum(1 for _, kind, _ in recipe if kind in ("class", "tuple"))
    runners = sum(1 for _, kind, _ in recipe if kind == "runner")
    unresolvable = 0
    for _, kind, payload in recipe:
        if kind == "class" and not payload[2]:
            unresolvable += 1
        elif kind == "tuple":
            unresolvable += sum(1 for _, _, ok in payload if not ok)
    return classes, runners, len(recipe) - classes - runners, unresolvable


def probe(case: Any, repeats: int, /) -> Probe:
    """Every phase of one case's construction, timed apart."""
    t = case.t
    clear_cache()
    node = node_for(t)
    if _is_pure_call_out(node):
        return Probe(name=case.name, compiles=False)
    call_outs = _call_out_nodes(node)
    out = _emit(node)
    source = out.source
    code = compile(source, "<generated>", "exec")
    blob = marshal.dumps(code)
    recipe = _recipe(out, call_outs)
    classes, runners, others, unresolvable = _counts(recipe)
    node_ns = _time(_cold(lambda: node_for(t)), repeats)
    decide_ns = _time(lambda: _is_pure_call_out(node), repeats)
    emit_ns = _time(lambda: _emit(node), repeats)
    compile_ns = _time(lambda: compile(source, "<generated>", "exec"), repeats)
    exec_ns = _time(lambda: exec(code, dict(out.globals)), repeats)
    build_ns = _time(_cold(lambda: compiled_validator(t)), repeats)
    composed_ns = _time(_cold(lambda: validator(t)), repeats)
    dumps_ns = _time(lambda: marshal.dumps(code), repeats)
    loads_ns = _time(lambda: marshal.loads(blob), repeats)
    recipe_ns = _time(lambda: _rebuild(recipe), repeats)
    return Probe(
        name=case.name,
        compiles=True,
        node_ns=node_ns,
        decide_ns=decide_ns,
        emit_ns=emit_ns,
        compile_ns=compile_ns,
        exec_ns=exec_ns,
        build_ns=build_ns,
        composed_ns=composed_ns,
        dumps_ns=dumps_ns,
        loads_ns=loads_ns,
        recipe_ns=recipe_ns,
        blob_bytes=len(blob),
        classes=classes,
        runners=runners,
        others=others,
        unresolvable=unresolvable,
    )


def _cold(build: Callable[[], Any], /) -> Callable[[], Any]:
    """Build from an empty cache, as a fresh process would."""

    def run() -> Any:
        clear_cache()
        return build()

    return run


def _us(ns: float, /) -> str:
    """Microseconds, or nanoseconds where microseconds would read as zero."""
    if ns < 1000:
        return f"{ns:.0f} ns"
    if ns < 1e6:
        return f"{ns / 1000:.1f} µs"
    return f"{ns / 1e6:.2f} ms"


def _import_ns() -> float:
    """
    What importing this library costs, as a yardstick for the whole result.

    A saving is only large or small next to something. Startup latency is what
    marshalling buys, so the honest comparison is against the other startup cost
    the same caller already pays without complaining.
    """
    times = []
    for _ in range(5):
        start = time.perf_counter()
        subprocess.run(
            [sys.executable, "-c", "import typing_validation"],
            capture_output=True,
            check=True,
        )
        base = time.perf_counter() - start
        start = time.perf_counter()
        subprocess.run(
            [sys.executable, "-c", ""], capture_output=True, check=True
        )
        empty = time.perf_counter() - start
        times.append(base - empty)
    return min(times) * 1e9


def render(probes: list[Probe], /) -> str:
    """The measurement, as a document that can be read without running it."""
    applicable = [p for p in probes if p.compiles]
    skipped = [p for p in probes if not p.compiles]
    total_build = sum(p.build_ns for p in applicable)
    total_load = sum(p.load_ns for p in applicable)
    total_composed = sum(p.composed_ns for p in applicable)
    imported = _import_ns()
    lines = [
        "# Marshalling: would it earn its risk?",
        "",
        "## The whole prize, in one place",
        "",
        f"Building every one of the {len(applicable)} compilable types in the "
        "corpus, in one process:",
        "",
        "| | cost |",
        "|:--|---:|",
        f"| `compiled_validator` for all of them, cold | {_us(total_build)} |",
        f"| the same, loaded from a marshalled cache | {_us(total_load)} |",
        f"| **saved** | **{_us(total_build - total_load)}** |",
        f"| `validator` for all of them, no cache needed | {_us(total_composed)} |",
        f"| importing `typing_validation` at all | {_us(imported)} |",
        "",
        "The last two rows are the ones that decide it, and neither is about "
        "the compiled path.",
        "",
        f"**Against `validator`.** A cache saves {_us(total_build - total_load)}"
        " over compiling, but a caller who simply composed instead would have "
        f"paid {_us(total_composed)} — within "
        f"{_us(abs(total_composed - total_load))} of the cache, with no cache. "
        "So the cache is not buying startup time, which was already available. "
        "It is buying the compiled path's *run* speed at the composed path's "
        "startup, and that is the only claim it can make.",
        "",
        f"**Against the import.** The whole saving is "
        f"{_us(total_build - total_load)}, and importing the library at all "
        f"costs {_us(imported)} — a ratio of "
        f"{(total_build - total_load) / imported:.1f}x. Read it as a scale, not "
        "a verdict: this is the entire corpus built in one process, so a caller "
        "with a handful of types has a proportionally smaller prize.",
        "",
        "Exploratory measurement, not part of the report. See the module "
        "docstring of `benchmark/marshalling.py` for what each phase is and "
        "why two of the four are unavoidable.",
        "",
        "## Where construction time goes",
        "",
        "`node` and `exec` are paid by a marshalled load too. Only `emit` and "
        "`compile` could ever be skipped.",
        "",
        "`sum/build` is the consistency check: the phases are timed separately "
        "and the build whole, so a row far from 100% moved between the two and "
        "should not be read.",
        "",
        "| Case | node | decide | emit | compile | exec | sum | cold build | sum/build | skippable |",
        "|:-----|-----:|-------:|-----:|--------:|-----:|----:|-----------:|----------:|----------:|",
    ]
    for p in applicable:
        lines.append(
            f"| {p.name} | {_us(p.node_ns)} | {_us(p.decide_ns)} | "
            f"{_us(p.emit_ns)} | {_us(p.compile_ns)} | {_us(p.exec_ns)} | "
            f"{_us(p.phases_ns)} | {_us(p.build_ns)} | "
            f"{p.phases_ns / p.build_ns:.0%} | {p.saved_ns / p.build_ns:.0%} |"
        )
    lines += [
        "",
        "## What a load would cost, and what it would save",
        "",
        "The load path is `node` + `unmarshal` + `recipe` + `exec`. The recipe "
        "is the globals rebuild: a class can never be a code constant, so every "
        "one the check names has to be resolved back by `module:qualname`.",
        "",
        "| Case | unmarshal | recipe | load total | cold build | net | blob |",
        "|:-----|----------:|-------:|-----------:|-----------:|----:|-----:|",
    ]
    for p in applicable:
        lines.append(
            f"| {p.name} | {_us(p.loads_ns)} | {_us(p.recipe_ns)} | "
            f"{_us(p.load_ns)} | {_us(p.build_ns)} | {p.share:+.0%} | "
            f"{p.blob_bytes} B |"
        )
    lines += [
        "",
        "## The comparison that decides it",
        "",
        "Marshalling's only coherent claim is *the compiled path's run speed at "
        "the composed path's build cost*. So the number a load has to beat is "
        "`validator(t)`, which a caller can already have without any cache at "
        "all. `load/composed` below 100% means the claim holds.",
        "",
        "| Case | marshalled load | `validator(t)` build | load/composed |",
        "|:-----|----------------:|---------------------:|--------------:|",
    ]
    for p in applicable:
        ratio = p.load_ns / p.composed_ns if p.composed_ns else 0.0
        lines.append(
            f"| {p.name} | {_us(p.load_ns)} | {_us(p.composed_ns)} | "
            f"{ratio:.0%} |"
        )
    lines += [
        "",
        "## What is in the globals",
        "",
        "A runner is a composed closure, which cannot be marshalled and has to "
        "be rebuilt from the node graph — the second, independent reason a load "
        "cannot skip `node`.",
        "",
        "`unresolvable` counts classes whose `module:qualname` does not lead "
        "back to them. Each is a type a real implementation would have to "
        "refuse to cache.",
        "",
        "| Case | classes | runners | other | unresolvable |",
        "|:-----|--------:|--------:|------:|-------------:|",
    ]
    for p in applicable:
        lines.append(
            f"| {p.name} | {p.classes} | {p.runners} | {p.others} | "
            f"{p.unresolvable} |"
        )
    if skipped:
        lines += [
            "",
            "## Cases with nothing to marshal",
            "",
            "`compiled_validator` returns `validator(t)` for these, so there is "
            "no code object. Marshalling does not apply, rather than failing.",
            "",
        ]
        lines += [f"- {p.name}" for p in skipped]
    return "\n".join(lines) + "\n"


def _in_subprocess(name: str, repeats: int, /) -> Probe:
    """
    Measure one case in a fresh interpreter.

    Not fastidiousness. Measured in one long process, this corpus disagrees with
    itself: ``TypedDict`` read 84 µs with 76% of its build skippable when probed
    alone and 241 µs with 58% when probed after fifteen other cases, because the
    phases and the whole build inflate at different rates as the heap grows. The
    ratios are the entire result, so a systematic drift that moves them is fatal
    rather than untidy. One process per case removes it.
    """
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmark.marshalling",
            "--case",
            name,
            "--repeats",
            str(repeats),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return Probe(**json.loads(out.stdout))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--filter", default="", help="only probe cases whose name contains this"
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=200,
        help="calls per timing round (default: 200)",
    )
    parser.add_argument(
        "--case",
        default=None,
        help="measure exactly this case and print JSON (used per subprocess)",
    )
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="measure every case in this process, which drifts — see _in_subprocess",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"write {FINDING.name} instead of printing",
    )
    args = parser.parse_args(argv)
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
    if args.case is not None:
        (case,) = [c for c in cases() if c.name == args.case]
        print(json.dumps(probe(case, args.repeats).as_dict()))
        return 0
    selected = [c for c in cases() if args.filter in c.name]
    probes = []
    for case in selected:
        print(f"  {case.name}", file=sys.stderr, flush=True)
        if args.in_process:
            probes.append(probe(case, args.repeats))
        else:
            probes.append(_in_subprocess(case.name, args.repeats))
    text = render(probes)
    if args.write:
        FINDING.write_text(text, encoding="utf-8")
        print(f"wrote {FINDING}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
