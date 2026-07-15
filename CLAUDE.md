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
| **2.1** | `validator` — closure composition | not started |
| **2.2** | `compiled_validator` — codegen via `exec` | not started |
| later | marshalling — persistent bytecode cache | blocked on an unsolved staleness problem (DESIGN.md §14) |

Each stage manufactures the oracle for the next, so the order is not negotiable: `validator` is conformance-tested against `validate`, and `compiled_validator` against both.

Every breaking change lands in 2.0. Stages 2 and 3 are purely additive.

### 2.1 milestones

Each gets a sub-branch off `main`, carries the tests that cover it, and is merged only once they pass.

| # | Milestone | Branch | Contents | Status |
|---|---|---|---|---|
| 1 | The compositor | `validator` | `validator(t)`: a closure per node form, composed over the interned graph; late binding at back-edges; `UnsupportedTypeError` raised eagerly at construction. Added to `MECHANISMS`, so the whole corpus and the deep-value tests run through it | not started |
| 2 | Break-even | `validator-benchmarks` | §11's unanswered number: how many values must be validated before `validator(t)` overtakes `validate`. Construction cost, per-call cost, and the crossover | not started |
| 3 | Release polish | `validator-docs` | README, guide, `DESIGN.md`, and the 2.1 release | not started |

**The composition shape is settled by measurement, and it is not what §3.3 assumed.** Composing closures that call each other directly is 3× faster than `validate` per node — and raises `RecursionError` on exactly the deeply nested values `validate` handles, which would make the two mechanisms disagree. Composing closures that push onto a shared work stack is safe and only 1.16× faster, which does not earn a second mechanism at all.

The resolution: **depth grows only at container boundaries.** A leaf check cannot descend, so a container calls its leaf children *directly* — free and safe — and pushes only children that can themselves descend. Measured at 2.9× `validate` on `list[int]`, while surviving a value nested twenty thousand deep.

## Owed, at the end of 2.2

- **How the benchmarks are presented.** With all three mechanisms in place the suite finally has something to compare, and printing it to a terminal stops being enough. Wanted: a **table artefact committed to the repo** — the numbers, the break-even points, and the captured environment, in a form a reader can consult without running anything. Raise it as its own round once `compiled_validator` lands; §11 says results are tracked over time rather than gated in CI, and this is what "tracked" should mean.

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
```

`mypy` and `pytest` are configured in `pyproject.toml` and need no arguments.
Docs build (needs Python 3.14 and the `docs` group):

```console
$ cd docs && python make-api.py && sphinx-build -M html . _build -W
```

`docs/api/*.rst` and `docs/api-toc.rst` are generated by `make-api.py` but **must be committed** — `.readthedocs.yaml` runs Sphinx directly and never invokes the generator.

The benchmark suite pulls v1 out of the `main` branch with `git archive` and imports it alongside, so the comparison runs in one process. **`validate` must not be slower than v1** — that is the one number that may never regress, and the runner says so explicitly at the end.

### Things CPython does that the house style does not expect

- **Exceptions always have a `__dict__`**, whatever `__slots__` says. The slots still keep it empty, which is what they buy; "no instance `__dict__`" is unachievable here.
- **mypy does not infer attributes assigned in `__new__`**, only in `__init__`. Slotted classes built with `__new__` therefore need annotation-only declarations in the class body. Annotation-only means no assignment, so the slot descriptors survive.
- **`typing.final` is not enforced at runtime.** It sets `__final__` and is otherwise a message to mypy.
