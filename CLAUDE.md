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
| **2.0** | `validate` and everything around it — the interpreter, node model, failure model, resolution, plugins, config | design done, not implemented |
| **2.1** | `validator` — closure composition | not started |
| **2.2** | `compiled_validator` — codegen via `exec` | not started |
| later | marshalling — persistent bytecode cache | blocked on an unsolved staleness problem (DESIGN.md §14) |

Each stage manufactures the oracle for the next, so the order is not negotiable: `validator` is conformance-tested against `validate`, and `compiled_validator` against both.

Every breaking change lands in 2.0. Stages 2 and 3 are purely additive.

### 2.0 milestones

Each gets a sub-branch off `v2`, carries the tests that cover it, and is merged only once those tests pass.

| # | Milestone | Branch | Contents | Status |
|---|---|---|---|---|
| 1 | Errors and dev tooling | `errors` | `ValidationError`, `UnsupportedTypeError`, the test and lint setup | done |
| 2 | Type resolution | `type-resolution` | annotation reading via `annotationlib`, qualifier stripping, forward-reference classification (§6) | not started |
| 3 | The interpreter, core forms | `validate-core` | the work stack, plain classes, `None`/`Any`, bare and parametric collections, mappings, tuples, unions, literals; `is_valid`, `validated`, `validated_iter`; the test corpus | not started |
| 4 | The interpreter, remaining forms | `validate-full` | `TypeVar`, `TypedDict`, `NamedTuple`, `Type[T]`, protocols, aliases, `Annotated`, `NewType`, forward refs, iterables; the plugin registry and `__validate__` hook (§7) | not started |
| 5 | The node model and configuration | `node-model` | interning, tiers, hash-cons recursion, totality memoisation, `can_validate`, `inspect_type` (§4, §3.5); the internal option manager (§8) | not started |
| 6 | Diagnosis | `diagnose` | the failure tree and the second traversal (§3.6, §5); **messages stubbed** pending the deferred format round | not started |
| 7 | The NumPy plugin | `numpy-plugin` | `typing_validation.numpy` (§7) | not started |
| 8 | Benchmarks | `benchmarks` | the suite of §11, including the comparison against v1 | not started |
| 9 | Release polish | `release-polish` | README usage, API docs, CI | not started |

The ordering is not arbitrary. `validate` (3, 4) lands before the node model (5) because §3.1 makes it genuinely independent of it — which then gives `can_validate` an oracle: a validator raises `UnsupportedTypeError` exactly when `can_validate` is `False`. `diagnose` (6) follows the node model because §4 makes it a method on the node.

Configuration rides with the node model because the cache's lifetime switches are its only client in 2.0, and because §8 has the option manager validate option values with our own `validate` — which by then exists.

## Invariants that are easy to break while coding

These are load-bearing. Violating any of them silently is how v1 got its bugs.

1. **`validate` stands alone.** No registry, no handler objects, no table dispatch, no attribute hops. It must not build an intermediate representation, and must never consult the validator cache — not even for a hit. It duplicates the semantics deliberately. (DESIGN.md §3.1)
2. **Interning is never semantically observable.** A cold, cleared or bypassed cache must not change any verdict. This is what makes unhashable types supported-but-unshared, forbids caller-frame resolution, and makes cache eviction safe. (§4.1)
3. **Validation is pure.** Never mutate or consume the value. Sequential union members, cross-mechanism agreement and the second diagnostic traversal all rest on this. (§2)
4. **Totality.** An unsupported component poisons the whole type. There is no partial mode. (TYPES.md)
5. **Validators never explain.** They fail hard; `diagnose` owns every message. The happy path pays nothing for diagnostics. (§5)
6. **Tests assert `ValidationError`, never `TypeError`.** A bare `except TypeError` is how v1's NamedTuple crash passed its own test suite for eleven releases. (§10)
7. **Zero runtime dependencies.** This library sits at the bottom of the stack; `optmanage` depends on *us*. (§8)

## Branches

Work for v2 lives on `v2`, branched from `main`. `main` still holds v1 (1.2.11).
Milestones get sub-branches off `v2`, merged back when the milestone completes.

## Deferred by agreement

- **The `diagnose` message format** is unsettled, and deferred until the end of the 2.0 implementation.
  When raising it: show 3–4 *complete* message families side by side, each covering a spread of cases (plain mismatch, failure at a collection index, failure at a mapping key, union with all members failing, missing required TypedDict key, unsupported type). Single examples flatter every format equally.

## Development

```console
$ uv sync --group dev --group docs
$ .venv/bin/python -m pytest
$ .venv/bin/python -m mypy
$ .venv/bin/python -m black typing_validation test
```

`mypy` and `pytest` are configured in `pyproject.toml` and need no arguments.
Docs build (needs Python 3.14 and the `docs` group):

```console
$ cd docs && python make-api.py && sphinx-build -M html . _build -W
```

`docs/api/*.rst` and `docs/api-toc.rst` are generated by `make-api.py` but **must be committed** — `.readthedocs.yaml` runs Sphinx directly and never invokes the generator.

Benchmarks are not yet set up; see DESIGN.md §11 for how they are meant to be structured.

### Things CPython does that the house style does not expect

- **Exceptions always have a `__dict__`**, whatever `__slots__` says. The slots still keep it empty, which is what they buy; "no instance `__dict__`" is unachievable here.
- **mypy does not infer attributes assigned in `__new__`**, only in `__init__`. Slotted classes built with `__new__` therefore need annotation-only declarations in the class body. Annotation-only means no assignment, so the slot descriptors survive.
- **`typing.final` is not enforced at runtime.** It sets `__final__` and is otherwise a message to mypy.
