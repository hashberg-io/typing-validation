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

## 3. Architecture

There are five mechanisms. Three validate:

| Mechanism | Cost to set up | Cost to run | For |
|---|---|---|---|
| `validate(val, t)` | none | good | validating a value once and moving on |
| `validator(t)` | low | better | validating many values against a fixed type |
| `compiled_validator(t)` | high | best | validating very many values against a fixed type |

And two explain:

| Mechanism | For |
|---|---|
| `inspect_type(t)` | what a type is, structurally, and whether it can be validated |
| `diagnose(val)` | why a validation failed, in detail |

All three validators share one contract: **return `True`, or raise `TypeError`**. They are interchangeable, and observably identical on every input. Choosing among them is a performance decision and nothing else.

### 3.1 The hot path and construction time

One specification, several implementations. The obvious move is to factor the common logic into a shared table or a registry of per-form handlers, and have each mechanism consume it. That move is wrong, and understanding why is the key to this design.

Indirection is not free, and on this hot path it is not cheap either. A dictionary lookup to find a handler, an attribute hop to reach its method, a bound-method call to invoke it — each is small, and each is paid *per node, per value, per call*. On `validate(12, int)` that overhead is the entire cost of the operation. A library whose whole purpose is to be fast enough to leave switched on cannot pay it.

So the line is not shared-versus-duplicated. **The line is hot path versus construction time.**

`validate` is the only hot mechanism. It is called once per value and forgets everything. It therefore **stands alone**: the type-form structure is written out explicitly in its body, with no registry, no handler objects, no table dispatch, and nothing that costs a lookup or an attribute access. It duplicates the semantics, deliberately.

`validator`, `compiled_validator`, `inspect_type` and `diagnose` all run at construction time or at failure time. Sharing between them is free, because it never touches a hot path — so they share freely, hanging off a single interned node class (§4).

Two corollaries fall out, and both matter.

**`validate` must not build an intermediate representation.** Constructing a node graph and then interpreting it would be clean, and would cost an allocation per node per call — precisely the overhead the split exists to avoid. `validate` dispatches directly on the raw `t` as it walks, materialising nothing.

**`validate` never consults the validator cache.** Not even to check for a hit. A cache lookup means hashing `t`, and `typing` objects do not hash cheaply. The separation is total: no mechanism ever calls into another's machinery, in either direction.

The duplication this licenses is only safe because of §10. Four independent implementations of one specification are four places to drift, and the drift is silent — a `compiled_validator` that disagrees with `validate` produces a wrong answer with no exception. **The conformance suite is not test hygiene here; it is the structural member that makes the architecture stand up.**

### 3.2 `validate`

```python
def validate(val: Any, t: Any, /) -> Literal[True]: ...
```

An interpreter. It walks the value and the type together in a single pass and answers yes or no.

**Non-recursive**, via an explicit work stack. The motivation is not elegance but correctness: what threatens the call stack is the nesting depth of the *value*, not of the type. `list[int]` is a shallow type, and a list nested two thousand deep is a legal value for `list[list[...]]`. A recursive walker would raise `RecursionError` — an error that is neither a validation failure nor an honest one. The work stack also avoids a Python call per node, which is the single largest avoidable cost in a walk like this.

Work items are `(value, type)` pairs. Conjunctive obligations — every item of a `list[int]`, every key and value of a `dict[K, V]` — are simply pushed, and the loop drains them. This is the overwhelmingly common case and it is where the flat loop pays off.

**Unions are the exception**, because they are disjunctive: any member may satisfy them. The mechanism is flag-gating. Members are tried in sequence; a flag is set once a member validates; later members are skipped by testing the flag; and if the flag is still unset when the members run out, validation fails.

The subtlety is that **a member attempt is a unit of success**, and the flag must be set by the unit completing — not by any individual obligation inside it. Given `list[int] | list[str]` and `[1, "a"]`, the `1` validating against `int` must not set the flag, because the attempt is not finished and will fail on `"a"`. A flat `(value, type)` stack has no representation of "this attempt", so one must be added: either a barrier marker that the loop drains down to, or a per-attempt scoreboard. It is cheap either way, but it does not fall out for nothing.

This is also where [purity](#2-validation-semantics) earns its keep. Trying members in sequence is only sound because a failed attempt leaves nothing behind.

**Most unions never reach that machinery.** Members that are plain classes collapse into a single `isinstance` call against a tuple: `int | None`, `str | bytes` and `int | str | None` — the overwhelmingly common shapes — become one `isinstance(val, (int, NoneType))` with no flag, no sequence and no attempts. Only parametrised members need sequential trial, so union handling is rare on real workloads.

**Failure is hard and cheap.** `validate` tracks no path, allocates no failure objects, and threads no context. It knows *that* it failed, not *where*, and hands `(val, t)` to §5 to find out. The happy path pays nothing for the diagnostics, which is what allows those diagnostics to be as rich as we like.

### 3.3 `validator`

```python
def validator(t: Any, /) -> Callable[[Any], Literal[True]]: ...
```

Builds a validation function specialised to a fixed type, by composing closures over the node graph (§4). Same contract as `validate`, same observable behaviour.

Construction is cheap, and **structurally shared**: because nodes are interned on `t` itself, `list[int]` is analysed once and its validator reused everywhere it occurs — inside `dict[str, list[int]]`, inside `tuple[list[int], ...]`, and inside any other type mentioning it. The validator graph is a DAG over distinct sub-types rather than a tree over syntactic occurrences.

**Recursion needs late binding, at back-edges only.** A validator for a recursive alias cannot capture its own validator at construction time, because it does not exist yet. The closure therefore reads the node's validator slot when called rather than capturing it. That is one indirection — paid only at the cycle, never on the acyclic majority of a type.

### 3.4 `compiled_validator`

```python
def compiled_validator(t: Any, /) -> Callable[[Any], Literal[True]]: ...
```

Emits Python source specialised to the type, `exec`s it, and returns the result. Same contract, same observable behaviour.

The goal is code equivalent to what a competent programmer would write by hand for that one type: flat, unrolled, with the `isinstance` checks inlined and no per-node dispatch of any kind. The cost is compile latency, paid once, deliberately, by a caller who has decided it is worth it.

**Unions are easier here than in the interpreter.** Emitted code is lexically scoped, so a member attempt is a block with its own local flag, and nothing unwinds:

```python
_ok_0 = False
if not _ok_0:
    _m = True
    if isinstance(v, list):
        for _i in v:
            if not isinstance(_i, int):
                _m = False
                break
    else:
        _m = False
    _ok_0 = _m
# ... next member, gated on _ok_0 ...
if not _ok_0:
    raise ...
```

Nested unions are handled by a variable-suffix convention, which is also what flattens the shared DAG back into distinct inlined occurrences.

**A cycle cannot be unrolled.** Unrolling a recursive alias does not terminate. So the emitted artifact is not one function but a small set of mutually-referencing ones — **one per recursion root** — with the back-edges becoming real calls. Since a cycle can only close through a *name* (§4.2), the roots are named things, and the emitted functions can carry meaningful names rather than counters.

**Unrolling needs a budget, because it works against sharing.** Sharing is what makes §3.3 cheap; unrolling destroys it by construction. A node referenced twenty times unrolls twenty times, and a nested `TypedDict` with forty fields explodes the emitted body. So the compiler needs an inlining policy — unroll small nodes, emit a call for large or heavily-shared ones — which is the classic inliner trade-off, with code size traded against call overhead.

The consequence is that `compiled_validator(t)` yields *a set of flat functions calling one another*, whose boundaries are chosen by budget and by recursion. That turns out to be convenient for the persistent-cache work (§12), where each function is separately a code object.

**Plugins are a de-optimisation boundary.** The compiler has no source for plugin-provided checks, so it can only emit a call into them (§7).

### 3.5 `inspect_type`

```python
def inspect_type(t: Any, /) -> TypeStructure: ...
```

Returns a structured description of a type: its shape, its components, and whether each is supported.

In v1 this was a side effect of a validation walk, obtained by passing an inspector *as the value* and having every branch record itself. In v2 it is a real artifact, built from the node graph, and the graph exists anyway to serve §3.3 and §3.4. Building one warms the other.

`can_validate(t) -> bool` is then the trivial predicate: whether the graph contains any unsupported node. Because "supported" is memoised per interned node (§2, §4.1), this is a lookup and not a walk.

When a type is unsupported, `inspect_type` reports the **whole** structure and marks precisely which component poisoned it. Totality means the answer is always "no", but it should never be an opaque "no".

### 3.6 `diagnose`

All three validators fail hard and say only *that* they failed. Everything a user reads about *why* is produced here, by a slower second traversal of the same `(val, t)`.

**This is the single most valuable consequence of the design.** Because diagnostics are produced in exactly one place, there is exactly one implementation of them — so the conformance obligation between mechanisms (§10) reduces to *"do they agree on the boolean?"*, which is a far smaller thing to police than "do they agree on the message". And because the second traversal only ever runs on a failure, which is by definition exceptional, it may be as slow, allocating and thorough as it likes.

`diagnose` is, in effect, v1's `validate` — recursive, allocating and rich — demoted from the hot path to diagnostics duty, where its costs stop mattering and its quality is the entire point.

It takes the value as well as the type, because the message must say *where* in the value the failure was: `invalid value at idx: 2`, inside `at key: 'a'`. A structural description of the type alone cannot say that.

The message format is deliberately unsettled. See §14.

## 4. The type node model

Everything in §3 except `validate` is built on one class: an **interned node**, one per distinct type, holding the type it was built from, its form, its interned children, and its memoised properties. `validator`, `compiled_validator`, `inspect_type` and `diagnose` are all methods on it.

That one class is simultaneously the unit of canonicalisation, the unit of deduplication, the thing `inspect_type` reports, the thing that emits a closure, the thing that emits source, and the thing that explains a failure. It can be all of those at once precisely because none of them is on a hot path (§3.1).

### 4.1 Interning

**The cache key is `t` itself. There is no canonicalisation pass.**

This is not a simplification we settled for; it is what the type surface asked for. The requirement was to preserve distinctions rather than dissolve them — an alias should report as itself, `Annotated` metadata must stay identity-bearing so that acting on it later remains possible, `NewType` should report as itself. Python's own type equality already does exactly that:

| Fact | Consequence |
|---|---|
| `MyInt == int` is `False` | aliases keep their identity |
| `UserId == int` is `False` | `NewType` keeps its identity |
| `Annotated[int, 'a'] == Annotated[int, 'b']` is `False` | metadata is identity-bearing |
| `list[int] == list[int]`, hashes equal | structural dedup is free |
| `Union[int, str] == Union[str, int]`, hashes equal | unions merge |

Unions are the *only* form Python merges, and it does the rest of the work too: nested unions flatten, `Union[int, int]` collapses to `int`, `Union[X]` degenerates to `X`, `Optional[X]` becomes `X | None`. So "normalise unions and nothing else" is not a rule we implement — **it is what falls out of using `t` as the key**, and the entire canonicalisation layer disappears.

Three problems dissolve with it. Aliases carry `__name__` (`repr(JSON)` is literally `JSON`), so recursion roots get real names for free — no non-identity-bearing label field, no walk-order dependence on which of two equal aliases wins. `NewType` carries `__supertype__`, so it displays as itself and checks as its supertype. And metadata is identity-bearing from day one, so the `Annotated` door stays open without a future cache-key migration.

Each node keeps the `t` it was built from, so display is `repr(t)`.

**The price**, paid knowingly: for unions the first-interned spelling wins the display, so `validate(x, Union[str, int])` may report `int | str`. This is forced — Python considers them equal and hashes them equally, so any cache keyed on `t` merges them — and defensible, since they *are* the same type.

#### Interning is never semantically observable

**This is a hard invariant, not an aspiration.** The cache may be cold, warm, cleared or bypassed, and no verdict may change. It has teeth in two places.

**Unhashable types skip the cache.** `Annotated[int, {"ge": 0}]` is unhashable, because metadata participates in the hash — and that is precisely the pydantic-style idiom the `Annotated` decision exists to accommodate, so it is not a corner case. Such a type simply builds a fresh node and forgoes sharing. It remains fully supported. v1's blanket refusal of unhashable types becomes unnecessary.

**Caller-frame resolution is forbidden.** It is this invariant, rather than taste, that rules out resolving inline forward references against the caller's frame: a node for `list["JSON"]` would then mean different things depending on which caller interned it first. See §6.

### 4.2 Recursion

The node graph is **not a DAG**. PEP 695 makes `type JSON = int | str | list[JSON] | dict[str, JSON]` idiomatic, so recursive types are ordinary rather than exotic, and each one puts a cycle in the graph.

Interning is what makes this tractable, which is a happy return on a decision made for other reasons. **Hash-cons before descending**: intern the node *before* building its children, so a back-edge finds the in-progress node and construction terminates.

**A cycle can only close through a name** — a PEP 695 alias or a forward reference — because a name is the only way a type can mention itself. Both are always hashable. So cycle roots are always in the cache, and cycle detection works even when unhashable leaves (§4.1) sit inside the cycle. The two rules do not collide.

Each mechanism then meets the back-edge differently, and the differences are the whole reason the mechanisms are separate:

| Mechanism | At a back-edge |
|---|---|
| `validate` | nothing; a work stack traverses a cycle without noticing |
| `validator` | late binding — read the node's validator slot at call time (§3.3) |
| `compiled_validator` | stop unrolling; emit a call to the root's function (§3.4) |

### 4.3 Lifetime and scoping

**By default the cache lives forever and holds strong references.** Types are usually module-level objects that outlive any cache anyway, so for the overwhelmingly common case there is nothing to manage and nothing to pay.

The exception is real, though. A strong reference to a type transitively pins the classes it mentions, and through them their modules and closures. A long-running process that builds types dynamically — synthesised `TypedDict`s, classes made in a factory, types built per request — accumulates them forever. So the cache is manageable:

- **Selective removal**, to drop a specific type's node.
- **A full clear.**
- **Scoped caching**, via a context manager, for callers who want the sharing without the retention.

Scoped caching is **tiered**. Entering the context pushes a new tier; while it is active, lookups consult the tiers innermost-first, and every new node is created in the innermost tier. Exiting drops that tier whole, in one operation, with no per-entry bookkeeping.

The tiering is sound because **references only ever point outward**. A node created while a tier is active lives in that tier and may reference nodes in enclosing tiers, which outlive it. Nothing in an enclosing tier can reference into an inner one, because while the inner tier is active it is where all new nodes go. So dropping a tier can never leave a dangling reference behind it.

And dropping a tier can never change an answer, only a cost — which is §4.1's invariant paying for itself a third time. That is what makes an eviction API safe to expose at all: without the invariant, "clear the cache" would be a semantic operation, and no user could be expected to reason about it.

The cache is a plain dictionary. See §13 on why that suffices.

## 5. Failure model

**Validators establish validity. They do not explain invalidity.** All three answer yes or no, and everything a user reads is produced afterwards, by `diagnose`, from the same `(val, t)`.

### The happy path pays nothing

This is the point of the arrangement. A validator tracks no path, threads no context, allocates no failure objects and formats no strings. It cannot tell you that the failure was at index 2 inside key `'a'`, because it never knew. On success — the case that dominates every real workload — the diagnostic apparatus costs exactly zero, which is what licenses it to be as thorough as we like on the rare occasions it runs.

The trade is a second traversal on failure. Failures are exceptional by definition, so paying twice for them is free in every sense that matters.

### Control flow is exception-free

v1 used exceptions for control flow: each union member was tried inside a `try`/`except TypeError`, and every nested failure raised, was caught, was repackaged and was re-raised on the way out. Raising is not cheap, and a union of *n* structured members failing costs *n* raise/catch cycles plus the repackaging at each level.

v2 raises **once**, at the very end, if at all. Union members are flag-gated (§3.2, §3.4), so a member failing is a boolean, not an exception. The interpreter's loop contains no exception handling whatsoever; it sets a flag and stops. The single `raise` happens above the loop.

### The exception

Validation failure raises a `TypeError` subclass carrying the structured failure tree as a proper attribute.

Being a `TypeError` subclass keeps the v1 contract — existing `except TypeError` handlers keep working — while the structure is reachable without v1's `setattr(error, "validation_failure", …)` smuggling. Programmatic access is then just an attribute on a caught exception, which is what `get_validation_failure` was for.

**`latest_validation_failure` and `get_validation_failure` are removed.** The first was backed by a module-level global *and* by `sys.last_value`, an interpreter-wide slot; it required being called immediately after the failure, cleared itself on read, and was unsound under any re-entrancy. The second is subsumed by an ordinary attribute access. Neither survives a design where the failure is simply attached to the exception you already caught.

### `is_valid` does not diagnose

```python
def is_valid(val: Any, t: Any, /) -> bool: ...
```

`is_valid` catches the hard failure and returns `False`. **It does not build the failure tree**, because a caller who wanted the explanation would have called `validate` and caught the exception. v1 set the global failure state here, which meant every `is_valid` miss paid for diagnostics nobody had asked for. A caller who wants the reason should use `validate`; a caller who wants a boolean should get a boolean at boolean prices.

### When the mechanisms disagree

There is one pathological case worth naming: a validator fails, `diagnose` re-walks the same value and finds nothing wrong.

That is a library bug — a mechanism has drifted from the catalogue — and it must be reported as one. `diagnose` must never respond to a reported failure with an implicit "actually, it's fine": the failure is not swallowed, and no `TypeError` is silently downgraded to success. It raises an internal error saying that validation failed but diagnosis could not reproduce it, and asks for a report.

This is exactly the drift §10 exists to prevent, and the reason the conformance suite is load-bearing rather than decorative.
