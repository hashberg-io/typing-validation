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

## 6. Type resolution

Some forms carry their component types in *annotations* rather than in `__args__`: `TypedDict` fields, `NamedTuple` fields. Reading those annotations is its own problem in 3.14, because PEP 649 made annotations lazily evaluated.

### `get_type_hints` is rejected

v1 used `get_type_hints`. It is the wrong tool, for one decisive reason: **it is all-or-nothing**. A single unresolvable field raises `NameError` for the whole class, and that `NameError` escapes from inside `validate` — neither a validation failure nor an `UnsupportedTypeError`, just a stray exception from a library the caller did not know was evaluating anything.

`annotationlib.get_annotations(t, format=FORWARDREF)` instead returns the unresolvable field as a `ForwardRef` object carrying its module. That turns an opaque crash into a precise report: *field `nested` of `TD` refers to unresolved name `Later`*. It also composes with totality — the unresolvable field poisons the `TypedDict`, and `inspect_type` points at the culprit.

### The cost we inherit

`get_type_hints` strips `Required`, `NotRequired` and `ReadOnly` for us. `annotationlib` does not:

```python
get_type_hints(TD)                        # {'a': int, 'b': str,             'c': bytes}
get_annotations(TD, format=VALUE)         # {'a': int, 'b': NotRequired[str], 'c': ReadOnly[bytes]}
```

So v2 strips the three qualifiers itself. This is new work, inherited by choosing the better resolution path — the observable behaviour is unchanged, but the obligation is real, and it is worth being clear that the `annotationlib` switch is not a pure win.

Requiredness is *not* re-derived from the qualifiers. It comes from `__required_keys__` and `__optional_keys__`, which the class computes for us and which remain correct under inheritance and `total=False`. The qualifiers in the annotation are redundant with those, so they are simply stripped. `ReadOnly` has no runtime meaning at all and is stripped for the same reason; `__readonly_keys__` is reported by `inspect_type` but never affects a verdict.

### Two reading paths, on the hot/construction line

Annotation access has two very different costs, and they fall either side of §3.1:

| Path | Cost | Used by |
|---|---|---|
| `t.__annotations__` | ~20 ns — PEP 649 caches the computed dict on the class | `validate` |
| `get_annotations(t, FORWARDREF)` | ~225 ns — recomputed per call | node construction (§4) |

`validate` reads the cached attribute, because paying 225 ns per call to re-derive a class's fields would be exactly the sort of overhead §3.1 exists to eliminate. Node construction pays the full price once, in exchange for the richer forward-reference handling, and never pays it again.

Both see the same content for the forms we read annotations from, which is what keeps the mechanisms conformant.

**One honest asymmetry.** Where a field is still an unresolved `ForwardRef`, `validate` must resolve it per call, since it caches nothing by construction. `validator(t)` resolves it once at construction and never again. That is a real cost difference on a real case — and it is precisely the difference `validator` exists to sell.

### Forward references

**A forward reference is resolvable iff it came from an annotation**, because that is what records a module to resolve against.

```python
ForwardRef('Later', module='mymod')   # from an annotation — resolvable
ForwardRef('JSON')                    # written inline    — no module, not resolvable
```

The two inline spellings do not even agree with each other: `list["JSON"]` stores the bare string `'JSON'`, while `typing.List["JSON"]` stores a module-less `ForwardRef`. Neither can be resolved, and both are unsupported.

**`validation_aliases` is removed.** It existed to paper over exactly this case, and the reason it cannot survive is structural rather than aesthetic: the only way to resolve an inline reference is against the caller's frame, which §4.1 forbids outright — an interned node for `list["JSON"]` would mean different things depending on which caller built it first, making interning observable. It is also incoherent for `validator(t)`, which is called from somewhere entirely unrelated to where `t` was written.

**PEP 695 absorbs the use case.** `type JSON = int | str | list[JSON]` is lazily evaluated, resolves against its defining module, needs no help from the caller, and is the recursion root the graph wants anyway (§4.2). The error message for an inline reference says so.

## 7. Extension points

### The hook already exists

Extensibility needs no new machinery, because the dispatch point is already there: **the generic-class branch** — the arm reached when a parametrised type's origin is a plain class the core knows nothing about. It is precisely where the core has run out of things it can determine on its own, and precisely where v1 gave up, next to a `# TODO` proposing a dunder classmethod.

**So the plugin mechanism and v1's TODO are the same feature.**

It is also free. `int`, `list[int]`, `dict[str, int]`, unions and literals all resolve long before that arm, so nothing that is not *already* unknown pays anything for its existence.

NumPy lands there naturally: `NDArray[np.uint8]` is `np.ndarray[tuple[Any, ...], np.dtype[np.uint8]]`, whose origin is `np.ndarray` — a plain class — so it falls through every other form and arrives exactly where the hook is.

### Two flavours, both needed

**`__validate__`, a dunder classmethod**, for classes you own. This is the ergonomic path for user code and the direct discharge of v1's TODO: a generic class declares how its own type arguments are validated.

**A registry**, for classes you do not own. `np.ndarray` cannot be given a dunder by us, so third-party types will always need registration. Neither flavour subsumes the other.

### What a plugin provides

The required interface is deliberately minimal: **give me a boolean**. Asking every plugin author to emit source for §3.4 would be an absurd toll for supporting one type.

Beyond that, a plugin may optionally supply:

- **Structure** — its component types, so `inspect_type` can report them and totality (§2) can propagate through them. NumPy needs this: `NDArray[np.uint8 | np.float32]` has a union inside it that the core validates.
- **Diagnostics** — so failures explain themselves in the plugin's own terms rather than generically.
- **An emitter** — for a sophisticated plugin that wants to be inlined by §3.4.

### Plugins are a de-optimisation boundary

`compiled_validator` has no source for a plugin's check, so it can only emit a **call** into it. A plugin therefore costs one function call in the compiled path, and the unrolling stops at its edge.

This is unavoidable — you cannot inline code you do not have — and it is worth stating plainly rather than discovering. A plugin that supplies an emitter escapes it; one that supplies only a boolean does not.

### Plugins must be imported explicitly

Without the import, a plugin's types raise `UnsupportedTypeError`, and the error names the import that would enable them.

The tempting alternative — enable automatically when the underlying library happens to be importable — is **rejected on determinism grounds**. It would make the supported surface depend on transitive imports: `can_validate(NDArray[np.uint8])` would answer `True` in a process where some unrelated dependency imported numpy and `False` in one where it did not. A predicate that users branch on must not behave that way, and the failure would be maddening to diagnose precisely because nothing in the user's own code would have changed.

It is worth noting the check is *self-gating* regardless: if numpy was never imported, `np.ndarray` does not exist as an object, so no type can hold it as an origin. A numpy type reaching `validate` is itself proof that numpy is imported. The explicit-import rule is therefore about determinism alone, not about avoiding an import cost.

### The hint table

To name the missing import, the error consults a small static table:

```python
{"numpy": "typing_validation.numpy"}
```

keyed by `t.__origin__.__module__.split(".")[0]`. That is a plain string comparison requiring no import at all.

The table is **behaviour-neutral by construction** — it is consulted only when building an error message that is being raised anyway, so a stale or missing entry costs helpfulness, never correctness. It cannot make validation wrong.

The table is ours for now. Letting plugins contribute entries is an obvious extension and deliberately deferred; ours-alone is simpler and nothing forecloses it.

### The messages

Every unregistered-generic error should teach, which v1's flat *"Unsupported validation for type X"* never did:

```
UnsupportedTypeError: Unsupported validation for type
numpy.ndarray[tuple[Any, ...], numpy.dtype[numpy.uint8]].
No validator is registered for generic class 'numpy.ndarray'.
NumPy support is available but not enabled: use 'import typing_validation.numpy'.
```

```
UnsupportedTypeError: Unsupported validation for type mylib.Matrix[int].
No validator is registered for generic class 'mylib.Matrix'.
Define a '__validate__' classmethod on the class, or register a validator
via typing_validation.register_validator(mylib.Matrix, ...).
```

The generic form names both flavours, so the error always states how to fix itself.

### NumPy is the first plugin

`typing_validation.numpy` ships in this distribution and provides `NDArray[dtype]` and `ndarray[shape, dtype]`.

Moving it out of the core is worth doing on its own merits — v1 put an `import numpy` probe in the middle of the dispatcher, which is an optional third-party dependency on the hot path, in a library that has no dependencies. But the stronger reason is that **it dogfoods the plugin API**. A plugin system whose author never uses it is always subtly wrong. NumPy is a punishing first client: dtype unions, shape tuples, parametrised origins like `np.number[Any]`. If the API can express NumPy, it can express what users will bring to it. Designing the API in a later release against imaginary clients would get it wrong, and by then numpy would be welded into the core and could only be extracted by a breaking change.

## 8. Configuration

The library needs a small settings surface — cache behaviour (§4.3), the inlining budget for §3.4, and whatever a future release adds.

### Why not `optmanage`

`optmanage` is the natural fit. It is designed for exactly this, its ergonomics are good, and its `__call__`-as-context-manager is precisely the shape §4.3's scoped caching wants. **It cannot be used, because it depends on this library.**

```
Requires-Dist: typing-validation >=1.2.4
Requires-Dist: typing-extensions >=4.6.0
```

`optmanage/option.py` opens with `from typing_validation import can_validate, validate`. That is a genuine cycle, and not merely an ugly line in the metadata: if a user imports `optmanage` first, `optmanage` begins initialising, imports `typing_validation`, which imports `optmanage` back out of `sys.modules` half-initialised, where `Option` is not yet bound. An order-dependent `ImportError`.

It would also drag `typing_extensions` back in transitively — the dependency §1 exists to have deleted.

The cycle is not incidental, either. `optmanage` validates option values *using this library*; runtime validation is its value proposition. There is no version of it that both keeps that and stops depending on us.

### What we do instead

A minimal internal option manager, **shaped like `optmanage`** because that shape is right: options as typed class attributes with defaults, validated on assignment, with a context manager for scoped overrides.

It validates option values with our own `validate`, which is pleasingly circular — it is exactly what `optmanage` does, and exactly why `optmanage` depends on us. We simply do it inside the boundary instead of across it.

The scope is deliberately small. This is a settings object, not a configuration framework, and it stays in proportion to a surface that currently amounts to a handful of switches. If it ever grows past that, the honest move is to reconsider, not to grow a framework inside a validation library.

The dependency direction is the general principle here: **this library sits at the bottom of the stack**, so anything it depends on must sit lower still. `optmanage` belongs *above* it, and using it here would invert the graph of our own projects.

## 9. Public API

```python
# validate a value
validate(val, t, /) -> Literal[True]                        # raises on failure
is_valid(val, t, /) -> bool                                 # no diagnostics (§5)
validated(val, t, /) -> T                                   # returns val
validated_iter(val, t, /) -> Iterable[T]                    # validates items as yielded

# build a reusable validator for a fixed type
validator(t, /) -> Callable[[Any], Literal[True]]           # §3.3
compiled_validator(t, /) -> Callable[[Any], Literal[True]]  # §3.4

# ask about a type
inspect_type(t, /) -> TypeStructure                         # §3.5
can_validate(t, /) -> bool

# extend
register_validator(cls, ...)                                # §7
# plus the __validate__ classmethod protocol

# errors
UnsupportedTypeError(NotImplementedError)
ValidationError(TypeError)                                  # carries the failure tree

# manage the cache
# clear, forget a type, scoped caching context manager      # §4.3
```

Arguments are **positional-only**. `val` and `t` are poor names to be permanently bound to, and nobody passes them by keyword.

### `validated_iter` survives on merit

It is not a convenience wrapper. It is the only honest way to validate an `Iterator[T]`: determining the items of a one-shot iterator consumes it, so [purity](#2-validation-semantics) forbids doing it eagerly, and `validated_iter` instead checks each item as it is yielded. It exists because the type system can express something the runtime cannot check without destroying it.

### Removed from v1

| Removed | Replacement | Why |
|---|---|---|
| `validation_aliases` | PEP 695 `type X = ...` | Its only use was inline forward references, which §6 shows cannot be resolved soundly. |
| `latest_validation_failure` | the exception's attribute | Backed by a module global *and* `sys.last_value`; had to be called immediately, cleared itself on read, unsound under re-entrancy. |
| `get_validation_failure` | the exception's attribute | Subsumed. It existed to un-smuggle what `setattr` had smuggled on. |
| `TypeInspector` | `inspect_type`'s return | v1's inspector was a value passed *into* `validate`; v2's is a real artifact (§3.5). |
| `UnsupportedType` | marking in the structure | The wrapper existed to mark unsupported nodes inside `TypeInspector`'s output. |

### Two promises v1 made, now kept

Neither of these is a break we chose; both are changes v1 documented as coming and never shipped.

**`can_validate` returns `bool`.** v1 returned a `TypeInspector`, relying on it being truthy, and carried the warning: *"The return type will be changed to `bool` in v1.3.0. To obtain a TypeInspector object, please use the newly introduced `inspect_type` instead."* The split is now real: `can_validate` answers a question, `inspect_type` returns a structure.

**`UnsupportedTypeError` extends `NotImplementedError`.** v1 extended `ValueError` with the warning: *"Currently extends ValueError for backwards compatibility. This will be changed to NotImplementedError in v1.3.0."* `NotImplementedError` is the honest base: an unsupported type is not a bad value, it is a thing this library has not implemented.

The distinction matters more than it looks. `UnsupportedTypeError` and `ValidationError` answer different questions — *"I cannot check this"* versus *"I checked this and it is wrong"* — and a caller must be able to tell them apart. Sharing a base with the validation error would blur exactly the line `can_validate` exists to draw.
