# typing-validation

Runtime validation of Python objects against type hints.
Version 2 is a ground-up redesign: Python 3.14+ only, LGPL-3.0-or-later, zero runtime dependencies.

## The design is written down. Read it before implementing.

- **[knowledge/TYPES.md](knowledge/TYPES.md)** — the catalogue of supported type forms and what validation means for each.
  This is the **specification**, not documentation of the code.
  The mechanisms share no implementation code, so this catalogue is the only thing binding them to a common meaning.
  **Where the code and the catalogue disagree, the catalogue is right.**
- **[knowledge/DESIGN.md](knowledge/DESIGN.md)** — the architecture: the mechanisms, how they are separated, and why.

The two are deliberately independent: the type surface can change without touching the architecture, and vice versa.
Keep them that way.

## Roadmap

| Release | Contents | Status |
|---|---|---|
| **2.0** | `validate` and everything around it — the interpreter, node model, failure model, resolution, plugins | **released** (tag `v2.0.0`) |
| **2.1** | `validator` — closure composition | **released** (tag `v2.1.0`) |
| **2.2** | `compiled_validator` — codegen via `exec` | **released** (tag `v2.2.0`) |
| **2.2.1** | patch: messages survive a value or type whose `__repr__` raises; `Type[T]` support decided from `T` alone | **released** (tag `v2.2.1`) |
| — | marshalling — persistent bytecode cache | **measured and declined.** Not blocked, not deferred: `benchmark/marshalling.py` measured what it would buy and the answer was milliseconds. See DESIGN.md §14 and *Marshalling* below |
| next | a runtime subtype relation | waits on Python 3.15 — see *Waiting on Python 3.15* |

Each stage manufactures the oracle for the next, so the order is not negotiable: `validator` is conformance-tested against `validate`, and `compiled_validator` against both.

Every breaking change lands in 2.0. Stages 2 and 3 are purely additive.

### Buildable now

With marshalling declined and the subtype relation waiting on an interpreter that does not exist yet, **the roadmap has no unblocked release on it.** These are the things that can be done anyway. Each is small, none is a milestone, and each is argued somewhere else in this file rather than here — this list is only a way in.

- **Namespace `__validate__`.** The strongest objection to the extension point is its name, and it does not depend on ever proposing anything upstream. It is the only bare dunder in the field: every peer either namespaces or uses no dunder at all. Breaking, so it wants a deprecation window and therefore wants starting early. See *Raised by the peer comparison* and [knowledge/GENERIC-ARGUMENTS.md](knowledge/GENERIC-ARGUMENTS.md).
- **Report the three findings owed upstream** — msgspec's recursive `Tree`, typedload's `AssertionError` from its own error path, beartype's `TypeHint` rejecting forms `is_bearable` accepts. Verified against installed sources, written up, and still unsent. Not code at all, which is why it keeps not happening. See *Raised by the peer comparison*.
- **Settle `Case.needs`.** Declared with a docstring arguing that a benchmark which silently skips is worse than one that says why, then never set and never read, while `_numpy_cases()` silently returns `[]`. Implement it or delete it; leaving it is a guarantee that does not exist. See *About the suite itself*.
- **Lower the benchmark's default `--repeats`.** 2000 now costs over ten minutes, which is why the full report is a pre-release ritual rather than something anyone runs. See *About the suite itself*.
- **Decide whether there is a `CHANGELOG`.** There is none, so three releases' user-visible history lives only in GitHub release notes, which are not in the repository and not diffable. Nothing depends on this and it has never been decided either way.

### What the three mechanisms turned out to be

Each release's design question was settled by **measuring before building**, and in both cases the measurement contradicted the design. Worth knowing before touching any of them.

**2.1 — `validator`.** §3.3 assumed closures that call one another. That is 3× `validate` and raises `RecursionError` once per level of the *value*, so it crashes on exactly what `validate` uses a work stack to survive. Closures that all push are safe and 1.16×, which earns no second mechanism. The answer: **depth grows only where a check can descend**, so a container *calls* the children that cannot and *pushes* the ones that can. "Can descend" belongs to the check, not to the node's children — a union of plain classes has members and still collapses to one `isinstance`.

**2.2 — `compiled_validator`.** Unrolling is safe because **an acyclic type bounds the value's depth**: `list[int]` against a value nested twenty thousand deep fails its `isinstance` at level two and never descends. A cycle removes the bound, so a back-edge stops unrolling and calls the composed validator. Same for a plugin, which has no source to inline. Where there is nothing to unroll at all, `compiled_validator(t)` **returns `validator(t)`** — wrapping it measured slower than being it.

**The inlining budget matters far less than §14 expects.** There is no cliff: cost is linear, and unrolling always repays (~1 value for `list[int]`, 465 for a forty-field `TypedDict`). It is a guard rail against a surprising stall, not a tuning knob. Two traps: it must count nodes **with multiplicity** (counting distinct nodes makes it do nothing, since interning means a tuple of twenty identical dictionaries has six), and **nesting is a second dimension** — CPython refuses more than ~20 statically nested blocks, which no node budget can see.

## Where to pick up

- **An unrolling fallback gate** was tried and rejected — see *The unrolling gate* below. Do not revive it without a run-time measurement, which coverage cannot substitute for.
- **The open issues have been triaged, and three of the six were already answered.** #21 asked for a prepared validator and got one in 2.1; #22 asked for PEP 695 `type` statements, which v2 supports as `TypeForm.ALIAS`; #24 reported that objects with a failing `__repr__` could not be validated, which v2 validates fine but could not *report on* until this was fixed. What remains is #11, #18 and #23, which are one milestone and not three — see *Waiting on Python 3.15*. The lesson worth keeping is that a ground-up rewrite closes issues silently, so an issue tracker predating it says nothing about the current code until each entry is re-run against it: two of the three were fixed years before anyone said so.
- **Marshalling was measured and declined**, and the reasoning is below under *Marshalling*. Do not reopen it as "the last unbuilt stage" — it is a closed question with numbers behind it, and `benchmark/MARSHALLING.md` holds them.
- **PyPI is current**: 2.0.0, 2.1.0 and 2.2.0 are all published. Stefano uploads from his own machine, with `python pypi-upload.py v<x.y.z>`, which builds from the tag rather than the working tree.
- **`benchmark/REPORT.md`** is regenerated by `python -m benchmark --write` and committed deliberately. CI does **not** check it is current, on purpose: a threshold on a noisy shared runner flakes and then gets disabled. **`benchmark/PEER-COMPARISON.md`** is the written synthesis over it, and is not generated.

## The unrolling gate: tried on a branch, rejected

An opt-in gate that fell `compiled_validator` back to `validator` when too little of a type's work was inlinable — scored by *coverage*, the visit-weighted share of emitted checks that are inline `isinstance`es rather than call-outs, each weighted `loop_weight ** loop_depth`. Built and measured on the `unrolling-policy` branch (an `Unrolling` config object, the coverage gate, an `unrolling_report` tool, a corpus safety sweep), then **abandoned and the branch deleted.** Two reasons it is not worth shipping:

- **It only ever saved build time, never run time.** Build is one-time and cached; the mechanism exists for types validated millions of times. The gate optimised the one cost the design already treats as free.
- **Coverage does not predict whether compiling helps.** The gain from compiling is the per-level structure *dispatch* it removes, which stays large even when a plugin or a deep call dominates raw run time — exactly where coverage reads low and the gate would fall back. So it would skip types that genuinely gain. (The benchmarks pointing this way were run on a busy machine and are not conclusive on magnitude; the reasoning is independent of them, and the default `compiled_validator` path is byte-for-byte unchanged and so at least as good either way.)

What survived and is merged here: the corrected nesting-ceiling comment in `emission.py` — the wall an unrolled chain of containers hits first is CPython's **~20 statically-nested-blocks** limit, not the 100-level indentation limit the old comment named. Earlier calibration figures (a clean "7 fall back, 0 wrongly") came from the same noisy timing and did not survive a careful look. If a fallback gate is proposed again, the answer is that coverage is the wrong signal: only a direct run-time measurement of compiled-vs-composed on the caller's own values could justify one, which is a profiling job, not a static rule.

## Marshalling: measured before it was built, and declined

The fourth stage was always a persistent cache for `compiled_validator`'s output, deferred behind an unsolved staleness problem.
It was measured instead of solved, and the measurement retired it.
`benchmark/marshalling.py` splits construction into its phases; `python -m benchmark.marshalling --write` regenerates `benchmark/MARSHALLING.md`.

**The cache would have worked.** `compile()` is 60–75% of a cold build, and a marshalled load skips 77–97% of one — the opposite of the guess that node-building would dominate and leave nothing worth caching.

**It still should not ship, and the reason is not staleness.** A marshalled load lands within ~300 µs of `validator(t)` across the whole corpus (448 µs against 758 µs), because rebuilding the node graph and resolving the globals is most of what composing a validator does anyway. So a cache cannot sell cheaper startup — `validator` already gives that away. Its only honest claim is *compiled's run speed at composed's startup*, and the whole of that, across all sixteen compilable types, is 6–8 ms, against 22–25 ms spent importing this library in the same process. Milliseconds, bought with the worst failure mode the library has.

Three findings that outlive the decision:

- **`__mro__` was never a staleness hazard.** DESIGN.md §12 named it for years. Every class check emits a live `isinstance`, so a re-based class moves a cached validator's answer exactly as it moves a fresh one's. The real hazard is only same-qualname-different-class.
- **Some types cannot be persisted at all.** `type(None)` reports its module as `builtins`, where `NoneType` does not exist, so a `module:qualname` recipe cannot name it. Any revival must refuse such types rather than write down a reference it cannot follow.
- **Deciding whether to compile is a phase in its own right** — `_is_pure_call_out` re-emits the whole body to compare it against a call-out, and costs a tenth to a fifth of the build. It was missing from the first split and showed up as an unexplained gap.

**Measure this corpus one process per case.** In one long process it disagrees with itself: `TypedDict` read 84 µs with 76% of its build skippable when probed alone and 241 µs with 58% after fifteen other cases, because the whole build and its phases inflate at different rates as the heap grows. When the result *is* a ratio, that drift is fatal rather than untidy.

## The rules the peer comparison is built on

**A benchmark of your own library, on your own corpus, scored against your own semantics will flatter you in ways that are invisible from the inside.** Every rule below is load-bearing against that, and each is cheap to break by accident while tidying something else.

- **Never total the corpus.** 17 of the 55 cases exercise `__validate__` or the NumPy plugin, which no peer implements. Folded into one percentage they put the next-best library thirty points behind us and read as a statement about the field, when their content is that we are the only library that is us. `Case.extension` carries the split; the report counts the halves apart. On the 38 shared cases typeguard with `ALL_ITEMS` is correct on every one, exactly as we are, and pydantic reaches 95% — that is the honest picture, and the claim to make is **reach**, never correctness.
- **Every rebuilding peer gets its alignment turned on**, because the tier is *defined* as the same verdict once coercion is off: pydantic `strict=True`, msgspec `strict=True`, typedload `basiccast=False`, cattrs with non-coercing structure hooks. cattrs is the trap — it has no strictness flag, which reads like an incapacity and is not one; its own `preconf` converters disable coercion by hook, and doing so costs it ~15%. A bare `Converter` posts a faster figure for an easier question.
- **Group by usage before tier.** Racing a prepared validator against an ad-hoc one measures the API chosen, not the library, and no caveat repairs it — the reader compares the columns in front of them.
- **Publish nothing that is not generated.** Records, geomeans and agreement counts all come out of `REPORT.md`; the written document quotes as little as it can and cites the rest. Hand-transcribed figures drift and cannot be re-derived: the msgspec `Tree` collapse is 16.7 ms / ~78× on one machine and 3.5 ms / 20.8× on another, and only the *effect* is portable.
- **Arrange it so we can lose, then check whether we did.** We do: trycast is 1.28× faster on `list[int] x1000`, and `compiled_validator` trails pydantic here at 0.92× having led at 1.11× on x86 Linux. Both belong in the document.
- **Verify every criticism of another project against its installed source before repeating it.** Each of these was: typeguard's default really is `FIRST_ITEM` sampling; beartype's `BeartypeStrategy.On` really is documented "currently unimplemented" and really does silently return the O(1) answer; the `Box("hi")` table in §7 reproduces exactly; msgspec really has no prepared in-memory API, and typeguard's `TypeCheckMemo` is a resolution scope rather than a cache, so ad-hoc is the honest classification for both rather than a convenience.

## Raised by the peer comparison, and not yet decided

None of these are committed to. They are the things the peer work surfaced that outlive it, parked here to be argued about rather than lost.

**About the suite itself**

- **`validate` is at parity with v1 on `NamedTuple`, and the regression check flickers.** On ARM64 Windows, `validate` measures 835/814/689 ns at 400/2000/5000 repeats against v1's 795/775/764 — so the same command answers "regressed" and "fine" on consecutive runs. This is pre-existing and independent of the restructure. Two separable questions: whether the case is a genuine near-regression worth fixing, and whether the check should have a tolerance band at all. It is currently a bare `v1 < validate` on two noisy figures, which is why the verdict is printed but deliberately **not** written into `REPORT.md` — a coin-flip in a committed diff teaches a reader to ignore the line that matters most.
- **`--repeats 2000` now costs over ten minutes.** One pipeline measures the mechanisms *and* ten peer configurations across two corpora, and msgspec re-analyses the type on every `convert` call. Lowering the default was already suggested by the peer work; the alternative is that the full report is simply a thing you run before a release and not otherwise.
- **The peer comparison's conclusions move with the hardware, and the corpus has only ever run on two machines.** `compiled_validator` against pydantic measured 1.11× on the x86 Linux container and 0.92× here; the sign of the headline flipped. The document now states the claim that survives both (within ~10%, direction machine-dependent), but a third machine — x86 Linux on real hardware, ideally — would settle whether that is the honest framing or a hedge. Everything else in `PEER-COMPARISON.md` is now generated into `REPORT.md` and cited rather than asserted, so a re-run tells you immediately what changed.
- **`validate` loses to trycast on `list[int] x1000`** — 89.7 µs against 114.2 µs, reproducibly, on an exact-tier ad-hoc peer doing identical work. Not a fairness problem; a real one. A thousand-element list is where per-node dispatch overhead is the entire cost, and it is the one shape where an interpreter loop beats us at our own question.
- **Every file read in the test suite now names its encoding**, which it did not until it was fixed: `test_docs.py` read Sphinx's output with the platform default, so cp1252 choked on the first non-ASCII byte and ten tests failed on Windows and nowhere else — CI never saw it, because that test runs only in the Ubuntu docs job. `test_style.py` had the same bug over Python sources, where a stray UTF-8 BOM surfaced as style violations rather than as an encoding problem; it reads `utf-8-sig`, which is what CPython itself does with a BOM'd source file. The lesson is the one CI cannot teach: a default-encoding read is a bug on some machine you are not sitting at. Still true regardless: **never edit a source file in this repo through PowerShell redirection**, because `Set-Content -Encoding UTF8` writes that BOM.
- **A regression could set the exit code.** Considered and not done: the suite is tracked over time rather than gated, and CI does not run it.
- **`Case.needs` is dead, and is the one thing it warns about.** The field is declared with a docstring arguing that "a benchmark that silently skips is worse than one that says why", and is then never set and never read — while `_numpy_cases()` silently returns `[]` when NumPy is absent, which is precisely the silent skip. Either implement it or delete it; leaving it reads as a guarantee that does not exist.
- **`PEER-COMPARISON.md` is curated prose living in `benchmark/`**, while the house convention puts curated prose in `knowledge/`. It leans on `TYPES.md` and `DESIGN.md` heavily. Left where it is because it is *about* the benchmark and reads next to what it cites.

**About the library, raised by what the comparison found**

- **Whether `compiled_validator` should fall back when little *worth* unrolling unrolls** was tried on a branch and rejected — see *The unrolling gate* above.
- **`__validate__` as the ecosystem's answer to generic arguments** is now written up in [knowledge/GENERIC-ARGUMENTS.md](knowledge/GENERIC-ARGUMENTS.md), with the record fetched from primary sources rather than recalled. Three things there change the shape of the question. The `TypeError` on `isinstance(x, list[int])` is **not** about erasure — that is folklore; the recorded reasons are Shannon's (a shallow answer masquerading as a deep one), PEP 585's (out of scope, and iteration is destructive), and Traut's (the runtime must not out-promise the static checker). PEP 585 kept `__args__` alive *specifically* so libraries could do this, and Guido told typeguard's author to go and build it — so this ground is assigned rather than neglected. And the strongest objection to the proposal is its **name**: Guido, in that same thread, "non-stdlib code should never use dunder names for anything other than their documented meaning". Every peer namespaces (`__get_pydantic_core_schema__`, `__beartype__`) or uses no dunder (cattrs' `register_structure_hook`); `__validate__` is the only bare one in the field. Namespacing it is the cheapest defensible move and should probably happen regardless of whether anything is ever proposed.
- **Should the tiering be published?** The ecosystem has no shared vocabulary for checking vs sampling vs rebuilding, and the absence is what lets benchmarks compare things that cannot be compared.
- **Three findings are owed upstream.** msgspec takes 16.7 ms on a 121-node recursive `Tree` *and* returns the wrong verdict on both recursive cases; typedload's `Loader` raises `AssertionError` from its own error path on `NamedTuple` while `typedload.load` raises cleanly; beartype's `TypeHint` rejects six type forms `is_bearable` accepts. None reported yet. Separately, and not a bug: `BeartypeStrategy.On` is documented in beartype's own source as unimplemented and silently returns the O(1) answer, so anyone benchmarking beartype as an exact checker by setting it measures a sampling library and believes otherwise.

## Waiting on Python 3.15

- **`typing.TypeForm` replaces the `typing_extensions` import.** PEP 747 is already adopted: `validated` takes `TypeForm[T]`, imported under `TYPE_CHECKING` so the library keeps zero runtime dependencies (typeshed carries the stub, so mypy needs nothing installed, and the docs read annotations as strings). The one cost is that `get_type_hints` on those functions raises `NameError` until the name exists at runtime. `test_typeform.py` fails deliberately when `typing.TypeForm` appears, and says what to change.
- **`TypeForm[T]` as a *checkable* type** — i.e. `validate(int | str, TypeForm[int | str])`. Not started, and not small: it means implementing PEP 747's subtyping rules, which is a genuinely different job from anything in 2.0 — every other form asks "is this value an X", this one asks "does this type form denote a subtype of X". It would subsume `_TYPE_ARG_EXPLANATION` in `validation.py`, since `Type[T]`'s restriction to classes and unions of classes exists precisely because `issubclass` cannot express the rest. Worth its own milestone, and worth deciding whether `Type[list[int]]` should then become supported.

  **Issues #11, #18 and #23 are all this milestone, and none of them is separable from it.** They read as three requests and are one: a subtype relation the library computes itself.
  #23 asks for `validate(list[int], type[list])` — a supertype check between parametrised generics.
  #18 asks to extend `Type[T]` to every `T` this library can validate, which is #23 stated as a scope rather than an example.
  #11 asks for `Callable` and `Protocol` with signature checks, and says outright that it needs a `validate_subtype` and #18 first — signature compatibility is subtyping, contravariant in the parameters.
  So the order is fixed: build the relation, and all three fall out. Doing any of them alone means inventing that relation privately in one arm, which is what `_TYPE_ARG_REASON` in `nodes.py` currently declines to do, in as many words.
  What is already done: `runtime_checkable` protocols validate today by `isinstance`, which is #11's *unparametrised* half, and the deliberate refusals are specified in `TYPES.md`.

## Settled, and worth not relitigating

- **The `diagnose` message format**: what was expected, `at:` where, `in:` what — the third dropped when the first has already named it. Chosen from four complete families rendered over the same spread of cases. Two rules find the place to report: through a union follow the member that got furthest, and report the type recorded at the deepest step rather than whatever the walk bottoms out in. See `diagnosis.py`.

## Development

```console
$ uv sync --group dev --group docs --group peers
$ .venv/bin/python -m pytest
$ .venv/bin/python -m mypy
$ .venv/bin/python -m black typing_validation test benchmark
$ .venv/bin/python -m benchmark            # add --filter to narrow
$ .venv/bin/python -m benchmark --write    # regenerate benchmark/REPORT.md
```

On Windows, which is where this is developed, the interpreter is `.venv\Scripts\python.exe`.

The `peers` group is the seven distributions behind the ten peer configurations the report's ecosystem half measures against, and it is separate from `dev` because the conformance suite does not need them and CI should not install them. Without it the suite still runs, and `--no-peers` skips that half outright.

`mypy` and `pytest` are configured in `pyproject.toml` and need no arguments.
Docs build (needs Python 3.14 and the `docs` group):

```console
$ cd docs && python make-api.py && sphinx-build -M html . _build -W
```

`docs/api/*.rst` and `docs/api-toc.rst` are generated by `make-api.py` but **must be committed** — `.readthedocs.yaml` runs Sphinx directly and never invokes the generator.

The benchmark suite pulls v1 out of the **`v1.2.12` tag** with `git archive` and imports it alongside, so the comparison runs in one process. A tag rather than a branch, deliberately: it read `main` until v2 landed there, at which point it would have compared v2 against itself and reported no regression for ever. **`validate` must not be slower than v1** — the one number that may never regress, and the runner says so at the end.

### Owed upstream to `sphinx-docscripts`

Two bugs found here, neither reported yet.

- **`autodoc_typehints.py` cannot parse a `Callable` parameter list.** `Callable[[Any], Literal[True]]` gives *"Found empty type name … annotation[start:stop] = '[Any]'"* — the nested list defeats the annotation parser. Worked around by naming the type: `type Validator = Callable[[Any], Literal[True]]`, which reads better anyway and is declared in `make-api.json`'s `type_aliases`.
- **The RST title underline is generated at the template's length**, not the project's, so any name longer than `PROJECT_NAME` (12 characters) under-runs its underline. `typing-validation` is 17.

### Things CPython does that the house style does not expect

- **Exceptions always have a `__dict__`**, whatever `__slots__` says. The slots still keep it empty, which is what they buy; "no instance `__dict__`" is unachievable here.
- **mypy does not infer attributes assigned in `__new__`**, only in `__init__`. Slotted classes built with `__new__` therefore need annotation-only declarations in the class body. Annotation-only means no assignment, so the slot descriptors survive.
- **`typing.final` is not enforced at runtime.** It sets `__final__` and is otherwise a message to mypy.
- **`except A, B:` in `benchmark/tools/v1.py` is correct, not a typo.** PEP 758 lets 3.14 drop the parentheses, and this project is 3.14-only. It reads exactly like the Python 2 syntax it is not, and it has already been "fixed" once by a tool old enough to reject it — black below 25.x cannot parse it. If something reports it as a syntax error, the something is out of date.
