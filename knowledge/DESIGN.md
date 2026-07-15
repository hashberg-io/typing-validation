# Design

The architecture of `typing-validation` v2: the mechanisms that validate values against type hints, how they relate, and why they are built the way they are.

This document covers *machinery*. The catalogue of which type forms are supported and what validation means for each lives in [TYPES.md](TYPES.md), and is deliberately separable: the type surface can be revised without touching the architecture, and vice versa.

## 1. Purpose and scope

`typing-validation` checks, at runtime, that a value conforms to a type hint.
Its contract is a single function:

```python
validate(val, t)   # returns True, or raises TypeError
```

The `True` return exists so that validation can be gated behind an assertion and compiled out entirely under `-O`:

```python
assert validate(val, t)
```

### What v2 keeps

The public shape of v1 survives, because it was right: `validate` for the raising form, `is_valid` for the boolean form, `validated` and `validated_iter` for expression contexts, `can_validate` for the support predicate, and `inspect_type` for structural introspection.

The rich, nested failure messages survive too. They are the library's best feature and its main differentiator, and no part of this redesign is permitted to degrade them.

### Why v2 is a rewrite rather than a refactor

v1 was structurally sound in its public shape and structurally flawed underneath.

The flaw was that **introspection and validation were the same code path**. `TypeInspector` was passed *as the value* into `validate`, and every branch of the dispatcher carried an `if isinstance(val, TypeInspector)` arm that recorded the type instead of checking it. One walk served two purposes. The consequences compounded: every new type form had to be implemented three times in lockstep — in the dispatcher, in the failure module, and in the inspector — and forgetting any one of them produced a silent gap rather than an error. The dispatcher grew into a single function of some two hundred lines with a linear chain of membership tests, and adding a form meant editing the chain in the right place, since the arms shadow one another.

That last hazard was not hypothetical. `abc.Iterable` ended up in two of the dispatcher's tables, the earlier one shadowed the later, and the item check for `Iterable[T]` became unreachable dead code — a bug that shipped through eleven releases. See [TYPES.md](TYPES.md) for the full adjudication.

There was also no extension point. A generic class's type arguments could not be validated at all, and a `# TODO` proposing a dunder classmethod sat in the source across those same eleven releases. NumPy, being unrepresentable through any extension route, was instead wired directly into the dispatcher — an `import numpy` probe in the middle of the hot path, on behalf of a dependency the library does not have.

None of this is fixable by refactoring, because the shape of the fix changes the shape of everything.

### What 3.14 deletes

v2 targets **Python 3.14 and above**, with no back-compatibility. This is not austerity; it removes a large fraction of v1 outright:

- Every `sys.version_info` branch, and the `typing_extensions` fallbacks behind them.
- The `typing.List`-versus-`list` duplication that pervaded the type tables.
- `use_UnionType`. 3.14 merged `types.UnionType` into `typing.Union`, so both spellings are the same object and there is no distinction left to track.
- Most of `validation_aliases`. PEP 695 makes `type X = ...` a first-class, lazily-evaluated, self-resolving alias, which is what that context manager was approximating.

And it adds `annotationlib` (PEP 649), which lets annotations be read without the all-or-nothing `NameError` that `get_type_hints` raises. See §6.

### What v2 adds

Three things, in order of significance:

- **Reusable validators.** `validator(t)` and `compiled_validator(t)` build a validation function specialised to a fixed type, for callers who validate the same type repeatedly and want to pay the analysis cost once. See §3.
- **Extension points.** A class can declare how its type arguments are validated, and types from libraries we do not own can be registered. NumPy becomes the first client of this rather than a special case in the core. See §7.
- **Structured type information** as a real artifact rather than a side effect of a validation walk. See §3.5.

### Constraints

**Zero runtime dependencies.** This library sits at the bottom of the stack and other libraries depend on it, so its dependency set is part of its contract. This is not merely a preference: `optmanage` — the natural candidate for the configuration surface in §8 — itself depends on `typing-validation`, so adopting it would create a genuine import cycle. See §8.

**Licensed LGPL-3.0-or-later.**

**No free-threading support.** See §13.

### Non-goals

`typing-validation` validates *types*, not *constraints*. It answers "is this value an `int`", never "is this value positive". Whether that stays true forever is deliberately left open — see [TYPES.md](TYPES.md) on `Annotated` — but nothing in 2.0 pursues it.

It is also not a coercion, parsing or serialisation library. It inspects values and reports; it never converts them.

## 2. Validation semantics

**The semantics live in [TYPES.md](TYPES.md).** This section exists to say why, and to state what that document governs.

Each mechanism in §3 implements validation independently, in whatever shape is fastest for it. They share no implementation code. What they share is a *meaning*: given the same value and the same type, they must reach the same verdict. That meaning has to be written down somewhere, and it cannot be written down in code without reintroducing the coupling §3.1 exists to avoid.

So `TYPES.md` is not documentation *of* the implementation. It is the specification the implementations answer to. **Where a mechanism and the catalogue disagree, the catalogue is right and the code is wrong** — that is the whole basis on which duplicated implementations are safe, and §10 exists to enforce it.

Two rules from that document constrain the architecture directly, so they are restated here.

**Totality.** If any component of a type is unsupported, the whole type is unsupported; there is no mode in which the checkable parts are checked and the rest waved through. Architecturally this means "supported" is a property computed once per type and propagated: an unsupported leaf poisons every type containing it. Because nodes are interned (§4.1), that computation is memoised for free, and `can_validate` is a lookup rather than a walk.

**Purity.** Validation never mutates or consumes the value it inspects. Three parts of this design rest on it. Union members are tried in sequence, and a member that fails part-way must leave nothing behind for the next to trip over (§3.2). The mechanisms must agree on every input, which they cannot do if checking changes what is being checked (§10). And a failed fast path hands the *same value* to `diagnose` for a second, slower traversal (§5) — which would be incoherent if the first traversal had disturbed it.

The forms that cannot honour purity are exactly the forms that need special API: a one-shot iterator cannot be inspected without being consumed, which is why `validated_iter` exists (§9).
