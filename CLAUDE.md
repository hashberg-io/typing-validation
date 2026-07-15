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
| **2.2** | `compiled_validator` — codegen via `exec` | **implemented**, unreleased |
| later | marshalling — persistent bytecode cache | blocked on an unsolved staleness problem (DESIGN.md §14) |

Each stage manufactures the oracle for the next, so the order is not negotiable: `validator` is conformance-tested against `validate`, and `compiled_validator` against both.

Every breaking change lands in 2.0. Stages 2 and 3 are purely additive.

### 2.1 milestones

Each gets a sub-branch off `main`, carries the tests that cover it, and is merged only once they pass.

| # | Milestone | Branch | Contents | Status |
|---|---|---|---|---|
| 1 | The compositor | `validator` | `validator(t)`: a closure per node form, composed over the interned graph; late binding at back-edges; `UnsupportedTypeError` raised eagerly at construction. Added to `MECHANISMS`, so the whole corpus and the deep-value tests run through it | done |
| 2 | Break-even | `validator-benchmarks` | §11's unanswered number: how many values must be validated before `validator(t)` overtakes `validate`. Construction cost, per-call cost, and the crossover | done |
| 3 | Release polish | `validator-docs` | README, guide, `DESIGN.md`, and the 2.1 release | done |

**The composition shape was settled by measurement, and it is not what §3.3 assumed** — see the section for the table. Closures that call one another are 3× `validate` and raise `RecursionError` on the deep values `validate` handles; closures that all push are safe and 1.16×, which earns nothing.

**Depth grows only where a check can descend.** So a container *calls* the children that cannot and *pushes* the ones that can: 2.75× `validate`, surviving twenty thousand levels. "Can descend" belongs to the *check*, not to the node's children — a union of plain classes has members and still collapses to one `isinstance`.

### 2.2 milestones

Each gets a sub-branch off `main`, carries the tests that cover it, and is merged only once they pass.

| # | Milestone | Branch | Contents | Status |
|---|---|---|---|---|
| 1 | Benchmark coverage | `compiled-benchmarks` | The cases that will judge the emitter, **before** it exists: heavily-shared types, which are what the inlining budget trades against and which nothing currently stresses; a NumPy case, since a plugin is a de-optimisation boundary and the only way to know its cost is to measure it; deep and recursive shapes | done |
| 2 | The emitter | `compiled-validator` | Source emission, `exec`, one function per recursion root, a call at every plugin. Added to `MECHANISMS` | done |
| 3 | The inlining budget | `inlining-budget` | Tuned against milestone 1's data, not against argument | done |
| 4 | Release polish | `compiled-docs` | README, guide, `DESIGN.md`, the 2.2 release — and the benchmark table, **discussed before it is executed** | done |

**The emitted shape, decided:** nested loops where the *type* bounds the depth, a stack at cycles.

This is the same fork 2.1 faced, one level up, and the same answer. It rests on an observation that only holds for emitted code: **for an acyclic type, the value can only nest as deep as the type says**, so fully-unrolled nested loops cannot recurse at all — `list[int]` against a value nested twenty thousand deep fails its `isinstance` at level two and never descends. Depth becomes unbounded only through a cycle, which is exactly where a back-edge must push instead of call.

**The bet paid.** Emitted code runs at 11.5 ns/node against a hand-written 11.1 — 5.1× `validate`, 1.86× `validator` — so §3.4's claim is measured rather than admired. A recursive alias or a plugin degrades to the composed validator, which is safe at any depth.

## Waiting on Python 3.15

- **`typing.TypeForm` replaces the `typing_extensions` import.** PEP 747 is already adopted: `validated` takes `TypeForm[T]`, imported under `TYPE_CHECKING` so the library keeps zero runtime dependencies (typeshed carries the stub, so mypy needs nothing installed, and the docs read annotations as strings). The one cost is that `get_type_hints` on those functions raises `NameError` until the name exists at runtime. `test_typeform.py` fails deliberately when `typing.TypeForm` appears, and says what to change.
- **`TypeForm[T]` as a *checkable* type** — i.e. `validate(int | str, TypeForm[int | str])`. Not started, and not small: it means implementing PEP 747's subtyping rules, which is a genuinely different job from anything in 2.0 — every other form asks "is this value an X", this one asks "does this type form denote a subtype of X". It would subsume `_TYPE_ARG_EXPLANATION` in `validation.py`, since `Type[T]`'s restriction to classes and unions of classes exists precisely because `issubclass` cannot express the rest. Worth its own milestone, and worth deciding whether `Type[list[int]]` should then become supported.

## Settled, and worth not relitigating

- **The `diagnose` message format**: what was expected, `at:` where, `in:` what — the third dropped when the first has already named it. Chosen from four complete families rendered over the same spread of cases. Two rules find the place to report: through a union follow the member that got furthest, and report the type recorded at the deepest step rather than whatever the walk bottoms out in. See `diagnosis.py`.

## Development

```console
$ uv sync --group dev --group docs
$ .venv/bin/python -m pytest
$ .venv/bin/python -m mypy
$ .venv/bin/python -m black typing_validation test benchmark
$ .venv/bin/python -m benchmark            # add --filter to narrow
$ .venv/bin/python -m benchmark --write    # regenerate benchmark/RESULTS.md
```

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
