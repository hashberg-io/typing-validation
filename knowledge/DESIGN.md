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

#### The closures do not simply call one another

That is the obvious composition, and this section assumed it. It is wrong, and the measurements say so plainly:

| Shape | `list[int]`×1000 | Deeply nested value |
|---|---|---|
| Closures that **call** one another | **19.4 ns/node** — 3× `validate` | `RecursionError` |
| Closures that all **push** to a work stack | 49.9 ns/node — 1.16× `validate` | fine |
| **Call what cannot descend, push what can** | **20.0 ns/node** — 2.9× `validate` | fine |

Calling recurses once per level of the **value**, so it raises `RecursionError` on exactly the values §3.2 uses a work stack to survive. Two mechanisms disagreeing about one value, one of them by crashing, is what §10 exists to prevent — and it is not an edge case, since a recursive alias over a deep document is the whole reason PEP 695 aliases are supported.

Pushing everything fixes that and surrenders the speed: 1.16× does not earn a second mechanism, and without the speed `validator` has no reason to exist.

The resolution is the third row, and it follows from one observation: **depth grows only where a check can descend.** A check that answers from the value alone cannot grow the stack, so calling it costs one call and risks nothing. So a container *calls* the children that cannot descend and *pushes* the ones that can. `list[int]` is a container over a leaf, so it takes the fast path; a recursive alias takes the safe one.

"Can descend" is a property of the **check**, not of the node's children. A union of plain classes has members and still collapses to a single `isinstance` against the argument tuple, so it can no more descend than `int` can, and a parent may call it. Getting this wrong is silent — a lost 3×, or a crash on deep values — so it is pinned by tests rather than trusted.

One consequence worth stating: the driver is still a loop with the same union flag-gating as §3.2. What `validator` removes is not the loop but the *dispatch* — every arm is chosen once, when the type is analysed, and the loop only calls what it is handed.

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

**Plugins are a de-optimisation boundary.** The compiler has no source for plugin-provided checks, so it can only emit a call into them (§7).

#### Why unrolling is safe at all, which this section never said

Unrolled loops nest once per level of the **type**, and for an acyclic type that bounds the **value**: `list[int]` against a value nested twenty thousand deep fails its `isinstance` at level two and never descends. So the emitted code cannot recurse, and can be exactly the nested loops one would write by hand.

A cycle removes the bound — a recursive alias accepts a value of any depth — and cannot be unrolled anyway. So a back-edge is where unrolling stops, and there the emitted code calls into §3.3's composed validator, whose driver is a loop and therefore safe at any depth. That is the same de-optimisation a plugin forces, for the same reason.

This is what makes the claim below true, and the measurement bears it out: **11.5 ns/node emitted against 11.1 hand-written** on `list[int]`, where §3.2 is 58.9 and §3.3 is 21.4.

#### The budget's premise was wrong, and it needed a second dimension

Three corrections, all from measuring.

**There is no cliff to tune around.** The trade this section describes — code size against call overhead — is real but one-sided. Cost is *linear* in emitted size (sixty wide `TypedDict`s unroll to fourteen thousand lines and forty milliseconds), and unrolling *always* wins on speed, repaying its build cost within about one value for `list[int]`, twenty-eight for `dict[str, int]`, eighty-five for a twenty-fold shared sub-type and four hundred and sixty-five for a forty-field `TypedDict`. For a mechanism premised on very many values, all of those are nothing. So the budget is generous, and its job is to stop a monstrous type spending tens of milliseconds in the compiler by surprise. A guard rail, not a tuning knob.

**It must count nodes with multiplicity.** Counting distinct nodes — the obvious reading of "unroll small nodes" — makes the budget do *nothing*: the graph is a DAG over distinct sub-types, so a tuple of twenty identical dictionaries has six of them and a hundred emitted ones. Every budget from 8 to 4096 produced byte-identical source until this was fixed. The quantity to bound is exactly the sharing that unrolling destroys.

**Nesting is a second dimension, and a hard one.** It guards two compile-time limits at once, and the tighter by far is that CPython refuses more than **~20 statically nested blocks** — each unrolled container opens a `for`, so a twenty-first nested inside the twentieth will not compile. Indentation is capped at 100 levels instead, which each `TypedDict` field's `if` consumes. A type a hundred containers deep is 101 nodes, comfortably inside any sane node budget, and unrolls into source that will not compile. So there is a nesting limit as well, far below both.

#### When there is nothing to compile, this *is* §3.3

A type with nothing to unroll — a literal, a structured union, a cycle, a plugin — would emit a function whose entire body is one call into the composed validator. That is §3.3 plus a function call, and it measures slower than §3.3: `Literal[1, 2, 3]` was 79 ns compiled against 71 composed. So `compiled_validator(t)` returns `validator(t)` outright in that case.

Which means the honest statement of what this mechanism buys is narrower than the section implies: **it is worth having exactly where there is structure to unroll.** The published table (`benchmark/REPORT.md`) says where that is, per type, and says `never` where it is not.

#### One function, not a set of them

An earlier draft expected *a set of flat functions calling one another*, one per recursion root, and noted that this would suit the persistent-cache work of §12, each function being separately a code object.

It emits **one** function. Recursion never needs a second, because a back-edge stops unrolling and calls the composed validator instead of an emitted peer — which is simpler, and already correct. §12 should not assume the multi-function shape; if marshalling wants it, it must ask for it.

### 3.5 `inspect_type`

```python
def inspect_type(t: Any, /) -> TypeNode: ...
```

Returns a structured description of a type: its shape, its components, and whether each is supported.

It returns **the node itself**, rather than a separate `TypeStructure` artifact built from it. §4 says the node model is *one class* that is simultaneously the unit of interning, the thing `inspect_type` reports, the thing that emits a closure and the thing that explains a failure — so a second class mirroring it would be a copy that could drift, and there is nothing to hide: every field the node carries is a field a caller asking about a type wants.

In v1 this was a side effect of a validation walk, obtained by passing an inspector *as the value* and having every branch record itself. In v2 it is a real artifact, built from the node graph, and the graph exists anyway to serve §3.3 and §3.4. Building one warms the other.

`can_validate(t) -> bool` is then the trivial predicate: whether the graph contains any unsupported node. Because "supported" is memoised per interned node (§2, §4.1), this is a lookup and not a walk.

When a type is unsupported, `inspect_type` reports the **whole** structure and marks precisely which component poisoned it. Totality means the answer is always "no", but it should never be an opaque "no".

### 3.6 `diagnose`

All three validators fail hard and say only *that* they failed. Everything a user reads about *why* is produced here, by a slower second traversal of the same `(val, t)`.

**This is the single most valuable consequence of the design.** Because diagnostics are produced in exactly one place, there is exactly one implementation of them — so the conformance obligation between mechanisms (§10) reduces to *"do they agree on the boolean?"*, which is a far smaller thing to police than "do they agree on the message". And because the second traversal only ever runs on a failure, which is by definition exceptional, it may be as slow, allocating and thorough as it likes.

`diagnose` is, in effect, v1's `validate` — allocating and rich — demoted from the hot path to diagnostics duty, where its costs stop mattering and its quality is the entire point.

It takes the value as well as the type, because the message must say *where* in the value the failure was: `invalid value at idx: 2`, inside `at key: 'a'`. A structural description of the type alone cannot say that.

**It is not recursive, though.** An earlier draft said it could be, reasoning that it runs only on failures and may therefore be as slow as it likes. Slow it may be; *deep* it may not, and the two are not the same freedom.

A failure tree is as deep as the **value**, for the same reason §3.2's walk is: the failing path through a list nested two thousand deep is two thousand levels long. A recursive `diagnose` would then raise `RecursionError` on exactly the values `validate` goes out of its way to handle — and it would raise it *on the way out of* an ordinary `ValidationError`, converting a correct verdict into a stack overflow. That is precisely the dishonest error the work stack exists to prevent, so diagnosis gets one too.

The same applies to everything that *reads* the tree — its `walk`, its `repr`, its `str`. A dataclass's generated `__repr__` recurses through its fields, so the tree cannot be a plain dataclass with `repr=True`: it would explode the moment anyone looked at it, including inside a debugger or a test runner. This is a small trap and it caught the first implementation.

The lesson generalises past this section: **iterative-because-the-value-is-deep is a property of every artifact shaped like the value**, not just of the validators.

The message format is settled. See §14.

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

Each node keeps the `t` it was built from, so display is `repr(t)` — guarded, since `t` is caller-supplied and its `__repr__` may raise. See §14.

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

`annotationlib.get_annotations(t, format=FORWARDREF)` instead hands back the unresolvable field as a `ForwardRef` object naming what it could not find. That turns an opaque crash into a precise report: *field `nested` of `TD` refers to unresolved name `Later`*. It also composes with totality — the unresolvable field poisons the `TypedDict` alone, and `inspect_type` points at the culprit.

The recursive resolution that `get_type_hints` performs must then be reimplemented, since `get_annotations` does not do it: it leaves the `'Later'` inside `list["Later"]` exactly as it found it. `typing._eval_type` is the engine that would do it, and is rejected as a private API that already carries a deprecation warning scheduled to become an error in 3.15. So the walk is ours, over the bounded set of forms this library supports.

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

**A forward reference is resolvable iff it came from an annotation**, because that is what identifies the owning class — and the owner is what identifies the module to resolve against.

The intuitive rule, that a reference is resolvable when *it* records a module, is wrong, and would strand most of the cases we need. Only a top-level `TypedDict` annotation records one:

| Written | Recorded as | Records a module |
|---|---|---|
| `class TD(TypedDict): x: "Later"` | `ForwardRef('Later', module='mymod')` | yes |
| `class NT(NamedTuple): x: "Later"` | `ForwardRef('Later')` | no |
| `class TD(TypedDict): x: list["Later"]` | `list['Later']` | no — it is a bare `str` |

So the module is recovered from the **owner** in every case, which is uniform and is the only thing that works for the bottom two. `ForwardRef.evaluate(owner=…)` falls back to the owner's module, so the mechanism is already there.

An inline `validate(x, list["JSON"])` records the *identical* bare string as the annotation in the third row. The two are indistinguishable as objects, and only the annotation can be resolved — which is the proof that resolvability is a property of the context, not of the reference.

#### Resolution happens before interning, not after

This is forced by §4.1's invariant rather than chosen for speed.

`list['Later']` is hashable, and equal to every other `list['Later']` in the process — including ones in other modules, meaning other classes. Interning it as a key would therefore merge references that resolve differently, and the verdict would depend on which owner happened to intern it first. That is precisely what "interning is never semantically observable" forbids.

So the annotation reader **rewrites** the annotation, replacing each reference with what it resolves to, and hands the node graph a fully resolved type. `list['Later']` becomes `list[Later]` before anything is keyed on it, and `list[Later]` means one thing everywhere. The node graph never sees an unresolved reference except an unresolvable one, which is unsupported and interned as itself.

**`validation_aliases` is removed.** It existed to paper over exactly this case, and the reason it cannot survive is structural rather than aesthetic: the only way to resolve an inline reference is against the caller's frame, which §4.1 forbids outright — an interned node for `list["JSON"]` would mean different things depending on which caller built it first, making interning observable. It is also incoherent for `validator(t)`, which is called from somewhere entirely unrelated to where `t` was written.

**PEP 695 absorbs the use case.** `type JSON = int | str | list[JSON]` is lazily evaluated, resolves against its defining module, needs no help from the caller, and is the recursion root the graph wants anyway (§4.2). The error message for an inline reference says so.

## 7. Extension points

### The hook already exists

Extensibility needs no new machinery, because the dispatch point is already there: **the generic-class branch** — the arm reached when a parametrised type's origin is a plain class the core knows nothing about. It is precisely where the core has run out of things it can determine on its own, and precisely where v1 gave up, next to a `# TODO` proposing a dunder classmethod.

**So the plugin mechanism and v1's TODO are the same feature.**

It is also free. `int`, `list[int]`, `dict[str, int]`, unions and literals all resolve long before that arm, so nothing that is not *already* unknown pays anything for its existence.

NumPy lands there naturally: `NDArray[np.uint8]` *is* `np.ndarray[_AnyShape, np.dtype[np.uint8]]`, whose origin is `np.ndarray` — a plain class — so it falls through every other form and arrives exactly where the hook is.

One step was missed in that account, and it costs nothing because another decision already paid for it. In modern NumPy `NDArray` is itself a **PEP 695 alias**, so `NDArray[np.uint8]` has origin `NDArray`, not `np.ndarray`, and only becomes an `ndarray` type after the alias substitutes its parameters. Supporting generic aliases (TYPES.md) is what makes that happen, so the hook is reached anyway — but the arrival is two hops, not one.

### Two flavours, both needed

**`__validate__`, a dunder classmethod**, for classes you own. This is the ergonomic path for user code and the direct discharge of v1's TODO: a generic class declares how its own type arguments are validated.

**A registry**, for classes you do not own. `np.ndarray` cannot be given a dunder by us, so third-party types will always need registration. Neither flavour subsumes the other.

### What a plugin provides

The required interface is deliberately minimal: **give me a boolean**. Asking every plugin author to emit source for §3.4 would be an absurd toll for supporting one type.

Beyond that, a plugin may optionally supply:

- **Structure** — which of its type arguments the core validates, so `inspect_type` can report them and totality (§2) can propagate through them.
- **Diagnostics** — so failures explain themselves in the plugin's own terms rather than generically.
- **An emitter** — for a sophisticated plugin that wants to be inlined by §3.4.

#### Structure is not optional in the way it looks, and the core cannot infer it

The obvious reading is that structure is a nicety, and that absent it the core can just treat every type argument as a component. Building the NumPy plugin shows that is wrong, and that the two are not the same thing at all.

**Not every type argument is a component.** `ndarray[shape, dtype]` has one of each:

| Argument | What it is |
|---|---|
| `tuple[int, int]` | an ordinary type, which the *core* checks the array's `.shape` tuple against |
| `np.dtype[np.uint8]` | a *specification the plugin interprets*, never a validation target |

Treating both as components makes `np.dtype[np.uint8]` one — and it is itself a parametrised NumPy class with no validator of its own, so totality poisons it, and with it **every array type there is**. `can_validate(NDArray[np.uint8])` would be `False` forever, with the plugin loaded.

So the plugin declares which arguments are components, and NumPy declares exactly one: the shape. That is also what makes shape validation free — the shape type goes straight back to the core, so a fixed rank and even `tuple[Literal[2], Literal[2]]` work with no shape logic in the plugin at all.

#### Registration must invalidate the cache

Registering a validator is the one operation that changes **what is supported**, and it therefore invalidates every interned node.

This is not housekeeping; it is §4.1's invariant. A node interned before `import typing_validation.numpy` records `NDArray[np.uint8]` as unsupported, and would go on saying so afterwards while a cold cache said otherwise — so the verdict would depend on whether anything had happened to ask first. Clearing everything is heavy-handed and exactly right: registration happens at import time and approximately never after.

Worth noting because it is the **only** hole ever found in "interning is never semantically observable", and it was found by using the API rather than by reasoning about it.

### Plugins are a de-optimisation boundary

`compiled_validator` has no source for a plugin's check, so it can only emit a **call** into it. A plugin therefore costs one function call in the compiled path, and the unrolling stops at its edge.

This is unavoidable — you cannot inline code you do not have — and it is worth stating plainly rather than discovering. A plugin that supplies an emitter escapes it; one that supplies only a boolean does not.

### Plugins must be imported explicitly

Without the import, a plugin's types raise `UnsupportedTypeError`, and the error names the import that would enable them.

The tempting alternative — enable automatically when the underlying library happens to be importable — is **rejected on determinism grounds**. It would make the supported surface depend on transitive imports: `can_validate(NDArray[np.uint8])` would answer `True` in a process where some unrelated dependency imported numpy and `False` in one where it did not. A predicate that users branch on must not behave that way, and the failure would be maddening to diagnose precisely because nothing in the user's own code would have changed.

It is worth noting the check is *self-gating* regardless: if numpy was never imported, `np.ndarray` does not exist as an object, so no type can hold it as an origin. A numpy type reaching `validate` is itself proof that numpy is imported. The explicit-import rule is therefore about determinism alone, not about avoiding an import cost.

### The plugin manifest

A small static table records which modules this distribution ships a plugin for:

```python
{"numpy": "typing_validation.numpy"}
```

keyed by `t.__origin__.__module__.split(".")[0]`. That is a plain string comparison requiring no import at all.

**It decides behaviour, and it is the only thing that can.** An earlier draft called it a hint table and claimed it was behaviour-neutral, consulted only to decorate an error that was being raised anyway. That is wrong, and the error was to think the two situations arriving at this arm are one situation.

They are not. An unregistered parametrised class is either:

- **`mylib.Matrix[int]`** — nothing could determine the arguments of a class we know nothing about. The type validates on its origin alone and the arguments go unchecked, which [TYPES.md](TYPES.md) specifies as the *meaning* of a generic class rather than a shortfall. Not an error.
- **`numpy.ndarray[shape, dtype]`** — the arguments *are* determinable, by a plugin sitting in this very distribution, unimported. Validating on the origin alone would return `True` for `validate(np.array([1.5]), NDArray[np.uint8])`. That is a totality violation: an obligation we could have discharged, silently skipped. An error.

Both reach this arm as "a parametrised class with no registered validator", and nothing about the *type* distinguishes them. Only the manifest does. So an entry here is a claim that support exists and merely needs enabling, and a **missing entry costs correctness, not helpfulness** — which is the opposite of what the earlier draft said, and worth being plain about.

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

### 2.0 ships no options at all

This section anticipated a handful of switches and said their contents would be discovered while implementing. Implementing found **none**, so 2.0 ships no option manager.

The two candidates both evaporated on inspection. Cache behaviour (§4.3) is an *API* — clear it, forget a type, scope it to a block — rather than a setting: each is a verb the caller invokes at a moment of their choosing, and none is a value read at validation time. The inlining budget (§3.4) is real, but it belongs to `compiled_validator` and therefore to 2.2.

So the manager arrives with its first genuine option, which on current evidence is that budget. Building it now would mean designing a settings surface against zero clients — the same mistake §7 refuses to make with the plugin API, and with less excuse, since unlike the plugin boundary this one is not architectural and can be added at any time without a breaking change.

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
inspect_type(t, /) -> TypeNode                              # §3.5
can_validate(t, /) -> bool

# extend
register_validator(cls, check, components=None)             # §7
# plus the __validate__ / __validate_components__ classmethods

# errors
UnsupportedTypeError(NotImplementedError)
ValidationError(TypeError)                                  # .failure is the tree

# read a failure
ValidationFailure                                           # val, t, detail, location, causes
Detail, Place, Location                                     # §3.6

# manage the cache
clear_cache()                                               # §4.3
forget_type(t) -> bool
scoped_cache()                                              # context manager
```

`TypeForm` and `TypeNode` are exported too, being what `inspect_type` returns.

`diagnose` itself is **not** exported. It is reached by catching a `ValidationError` and reading `.failure`, which is the only context in which its answer means anything — and, as §5 notes, the one place it must never be asked about a value that is actually valid.

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

## 10. Testing and conformance

### The stakes

Several independent implementations of one specification are several places to drift, and **the drift is silent**. A `compiled_validator` that disagrees with `validate` on some corner returns a wrong answer with no exception and no symptom.

So this suite is not test hygiene. It is the structural member that makes §3.1 stand up: the deliberate duplication is only safe because something continuously proves the implementations still agree. It is designed here, in this document, rather than bolted on afterwards.

### Assert the failure is *our* failure

**The most important rule, and the one v1 learned the hard way.**

v1's sweep tested rejection like this:

```python
for t in [t for t in _all_types if t not in ts]:
    try:
        validate(val, t)
        assert False, "shouldn't have been an instance"
    except TypeError:
        pass                      # <-- any TypeError counts as success
```

`_all_types` included `typing.NamedTuple`, which is not a runtime type, so `validate(val, typing.NamedTuple)` raised a raw `TypeError: isinstance() arg 2 must be a type…` from inside `isinstance`. The bare `except TypeError` read that as a correct rejection, and the test passed. **The bug and its camouflage shipped together, through eleven releases.**

Hence the rule: a test asserts `ValidationError`, never `TypeError`, and never uses a bare `except`. A test that catches the base class cannot distinguish *"correctly rejected the value"* from *"the library crashed"*, which is precisely how that bug survived.

This is why `ValidationError` is a distinct subclass (§5) rather than a plain `TypeError` with data smuggled onto it. The exception design and the test rule are the same decision seen from two sides: the type system of the errors is what makes the tests able to tell truth from accident.

### Structure

**A corpus module owns the cases.** v1 put its case tables in `test_00_validate.py` and had `test_01_can_validate.py` do `from .test_00_validate import _test_cases, …` — one test file reaching into another's privates, which is why the files are numbered at all. The numbering was load-bearing, and it still has a hole where `test_02` used to be. A `test/cases.py` owning the corpus makes the ordering irrelevant and the numbering unnecessary.

The corpus is organised **per type form**, mirroring [TYPES.md](TYPES.md), so that a change to the catalogue has one obvious place to land. Each form contributes valid `(val, t)` pairs and invalid ones.

**The mechanism axis.** The corpus is crossed with `[validate, validator, compiled_validator]`, so every case runs through every mechanism automatically:

```python
@pytest.mark.parametrize("mechanism", ALL_MECHANISMS)
@pytest.mark.parametrize("val, t", VALID_CASES)
```

Drift then cannot land silently — it cannot land at all without turning something red. Adding a fourth mechanism later means adding one entry to a list, not writing a fourth suite.

**The complement trick, kept.** v1's `test_invalid_cases` derived failures as *"every type in the universe not in this case's list must reject this value"*. That is a genuinely strong property from a small corpus, and it generalises across the mechanism axis for free. It is retained — with the `except TypeError` replaced by `pytest.raises(ValidationError)`, which is what would have caught the NamedTuple bug on the day it was written.

### The obligation is smaller than it looks

Because all mechanisms fail hard and delegate to one `diagnose` (§3.6), **there is exactly one implementation of error messages**. Conformance therefore only has to police the *boolean*. Message formatting is tested once, against `diagnose`, and no cross-mechanism agreement about text is required at all.

### Differential testing

The curated corpus proves the cases we thought of. Generated `(val, t)` pairs, checked for agreement across mechanisms, probe the ones we did not — which, given that the whole architecture rests on the mechanisms agreeing, is worth doing properly. The invariants are cheap to state: **for every `t` with `can_validate(t)`**, all mechanisms agree on the verdict for every value; validation never mutates its input.

That qualifier is load-bearing rather than a hedge. Where `can_validate(t)` is false the mechanisms genuinely differ, and must: `validate` walks value and type together and raises when it *reaches* the unsupported component, while `validator(t)` analyses the whole type before seeing a value and raises at construction. So `validate([], list[Callable[[int], int]])` returns `True` where `validator(list[Callable[[int], int]])` refuses to build at all. Neither is wrong; agreement is only meaningful where the type is honoured. [TYPES.md](TYPES.md) states the rule and why `validate` is not made eager.

That last one deserves a real test rather than a convention, since [purity](#2-validation-semantics) is assumed by three separate parts of this design.

### Staging helps

The implementation order in §12 means each mechanism is conformance-tested against a working predecessor: `validator` against `validate`, and `compiled_validator` against both. There is never a moment when two unproven implementations are being compared to each other.

## 11. Benchmarking

**The benchmark suite is a deliverable, not a diagnostic.** The entire justification for having three validators is performance. Without measurement, that justification is a hypothesis and the extra two mechanisms are unexplained complexity. The suite is what converts the design's central claim into something falsifiable.

### What v1 measured, and why it did not work

v1's `benchmark.py` described itself, accurately, as *"rough and messy basic benchmarking code"*. Its problems are worth naming, because they are the specification for what to do instead.

**The unit was wrong.** It reported *nanoseconds per byte*, dividing elapsed time by `sys.getsizeof` of the data. But validation work is proportional to the number of type-nodes visited, not to bytes occupied, and the two are unrelated:

- Validating any `int` against `int` is exactly one `isinstance` call, while `sys.getsizeof` of an integer ranges from 28 to 72 bytes with its magnitude. The reported figure moves 2.6× while the work is constant.
- Across types the ratio is incommensurable: `int` carries 28 bytes per unit of work, `bytes(20)` carries 53, and a 20-element `list[int]` carries 10.3. So v1's headline figures — `0.431 ns/B` for `list` against `4.817 ns/B` for `int` — do not mean list validation is eleven times faster. They mean lists have more bytes per `isinstance` call. The numbers cannot be compared to each other at all.

**The union figure was fudged.** Byte counts were multiplied by the number of union members *"for uniformity of comparison"*, which is a correction with no principle behind it.

**Nothing was reproducible.** Seeds came from `int(time())`, so no two runs measured the same data and no run could be re-examined.

**There was no meaningful baseline.** `sumprod` and `append` establish that Python does arithmetic, not whether validation is fast.

### Units

- **Nanoseconds per call**, for a fixed type and value — the number a user actually experiences.
- **Nanoseconds per type-node visited**, for comparing across shapes — the closest thing to a unit of work, and what `ns/B` was groping toward.

Both are reported. Neither is divided by anything the caller does not control.

### Baselines

Each measurement is stated against something meaningful:

| Baseline | Answers |
|---|---|
| **A hand-written validator** for that exact type | Does `compiled_validator` deliver what it claims? |
| **Bare `isinstance`** | The absolute floor for a scalar check. |
| **v1**, where the types are comparable | Did the rewrite regress anything? |

The hand-written baseline is the important one, because §3.4's claim is precise and therefore falsifiable: *code as if you wrote it yourself, modulo a single function call*. That claim should be tested directly rather than admired. If a compiled validator is materially slower than the hand-written equivalent, the inlining budget or the emitter is wrong, and the benchmark should be what says so.

### The break-even point

For each type, the suite reports **how many values must be validated before `validator(t)` overtakes `validate`, and before `compiled_validator(t)` overtakes `validator(t)`.**

Given a per-call cost and a construction cost, this is arithmetic. But it is the only number that answers the question a user actually has — *"which of these three should I use?"* — and it turns the choice from folklore into a lookup. A `compiled_validator` that only pays for itself after ten million values is a fact worth publishing, in either direction.

### Coverage

Scalars; flat collections; deeply nested collections; mappings; fixed and variadic tuples; unions of plain classes (the `isinstance`-tuple fast path of §3.2) *and* unions of structured members (the sequential-attempt path), because those are different mechanisms and must not be averaged together; `TypedDict`s, including the annotation-resolution cost of §6; and recursive aliases, where §3.4 must stop unrolling.

**Both outcomes are measured.** The success path is the one that matters, but §5's failure path pays for a *second traversal*, and that cost is currently an assumption — "failures are exceptional, so paying twice is free". Assumptions in a performance argument are exactly what benchmarks are for.

### Hygiene

Fixed seeds. Captured environment — Python build, machine, versions — because a number without its context is unreadable six months later. Results tracked over time rather than gated in CI, since a hard threshold on a noisy shared runner produces flakes and then gets disabled, which is worse than not having it.

### The number that matters most

**`validate` must not be slower than v1.** It is the function that everybody calls and most people will only ever call. If the redesign buys two new mechanisms at the cost of making the common path slower, it has failed, regardless of what the other two achieve. That comparison is the first benchmark to exist and the last one allowed to regress.

## 12. Implementation staging

Four stages, strictly ordered. **Each stage manufactures the oracle for the next** — which is the whole reason the order is not negotiable.

### Stage 1 — the interpreter

The node model (§4), `validate` (§3.2), the failure model (§5), `diagnose`, `inspect_type`, `can_validate`, `is_valid`, `validated`, `validated_iter`, type resolution (§6), the plugin boundary with the NumPy plugin (§7), and configuration (§8).

Plus the conformance harness (§10) with one mechanism on its axis, and the benchmark comparison against v1 (§11).

This stage is **already a complete library**: v1's surface, modernised, with the defects in [TYPES.md](TYPES.md) fixed. Nothing after it is required for the library to be useful — the later stages are performance, offered to callers who ask.

The plugin boundary belongs here rather than later, despite being new. It is architectural, not a feature: deciding it afterwards would mean either welding NumPy into the core permanently or extracting it via a breaking change. And it costs little now, because §7's hook point already exists.

### Stage 2 — `validator`

Closure composition over the node graph (§3.3), and late binding at back-edges.

The node graph already exists from stage 1, since `inspect_type` and `diagnose` need it. This stage adds a method to it.

`validate` is the oracle: every case in the corpus must reach the same verdict through both. This is the moment the mechanism axis (§10) earns its design — adding `validator` to the suite is adding one entry to a list.

### Stage 3 — `compiled_validator`

Source emission, `exec`, the inlining budget, one function per recursion root (§3.4).

Both `validate` and `validator` are oracles. Two independent implementations already agree; a third must join them.

This is where the design is most likely to be wrong, because the inlining budget is a real compiler decision made on guesses. §11's hand-written baseline and break-even numbers are what turn those guesses into evidence.

### Stage 4 — marshalling

A persistent cache for stage 3's output, so that compile latency is paid once across processes rather than once per process.

The **mechanism** is settled. `marshal` handles code objects, but `co_consts` admits only `None`, `bool`, `int`, `float`, `complex`, `str`, `bytes`, `tuple`, `frozenset`, `code` and `Ellipsis`. A type — `int`, a user class, an enum member inside a `Literal` — can never be a constant; in generated source it compiles to a `LOAD_GLOBAL` resolved against the globals handed to `exec`. So the persisted artifact is two parts: **the marshalled code, plus a recipe for rebuilding its environment** — a mapping from generated names to either inline marshalable constants or resolvable references like `module:qualname`.

This section was written expecting §3.4 to emit a *set* of mutually-referencing functions, one per recursion root, each separately a code object, so that the recipe could map names to them with cycles included. **It emits one function.** Marshalling must not assume otherwise: there is a single code object to persist, and the back-edges a cycle needs are closed inside it rather than across a set of names. See §3.4.

The **hard part is unsolved, and it is why this is last.** Staleness. What invalidates a cached validator for `list[MyClass]`? The class's identity does not survive across processes. Its `__mro__` may have changed since the bytecode was written. After a refactor, a *different* class can hold the same qualified name — and then the cached validator is silently wrong, which is the worst failure mode this library has. `__pycache__` solves the analogous problem with source path, mtime and size; our inputs are not files, so that answer does not transfer. There is no design here yet, only a requirement: **a stale entry must be detected, never trusted.**

Deferring is not procrastination. Stage 3 is the oracle: a marshalled validator must behave identically to a freshly-compiled one, and that test cannot be written until freshly-compiled ones are known to be right.

### Release boundaries

The stages *are* the releases:

| Release | Contents |
|---|---|
| **2.0** | Stage 1 — `validate` and everything around it |
| **2.1** | Stage 2 — `validator` |
| **2.2** | Stage 3 — `compiled_validator` |
| later | Stage 4 — marshalling |

**Every breaking change lands in 2.0**: the API removals of §9, the corrections in [TYPES.md](TYPES.md), the 3.14 floor. Stages 2 and 3 are purely additive and fit under semantic versioning without a further major bump, so users absorb the breaks once, early, rather than waiting behind work whose schedule is unknown. The unsolved staleness problem then blocks no release at all.

Aligning the two boundaries also keeps each release honest: one release is exactly one mechanism, conformance-tested against its predecessors and benchmarked against the baseline that justifies its existence. A release that cannot demonstrate it earns its complexity does not ship.

## 13. Assumptions and non-goals

Written down because an assumption nobody recorded is one nobody can notice going stale.

### No free-threading support

The intern cache is a plain dictionary, and we rely on the GIL.

Worth being precise about what that costs, because the answer is not what one would guess. Under a free-threaded build, two threads racing to intern the same type would each build a node and one would win — and by §4.1's invariant that is **a wasted allocation, not a wrong answer**. Interning is never semantically observable, so even a thoroughly racy cache stays correct. Most of what looks alarming here is benign.

The exception is precise and worth recording, because it is the thing that would actually need doing: **hash-cons-before-descending** (§4.2) publishes a node *before* its children exist, so that back-edges can find it. Under concurrency, another thread can look up that type and receive a node that is not yet built. That is a genuine correctness hazard, it lives at exactly one point in the design, and it is where free-threading support would have to start.

Validation itself is [pure](#2-validation-semantics) and therefore thread-safe on the value side. The cache is the only shared mutable state in the library.

### Types are immutable once used

**A type's meaning must not change after it has been validated against.**

This is a real constraint and not a pedantic one, because violating it breaks the mechanisms' equivalence — the property everything else rests on. `validate` reads a `TypedDict`'s annotations live on each call (§6), while `validator(t)` snapshots them at construction. Mutate `TD.__annotations__` between the two and they will disagree: the interpreter sees the new fields, the constructed validator sees the old. Both are behaving correctly; the assumption underneath them has been violated.

So mutating a class's annotations, bases or fields after validating against it is undefined behaviour. In practice types are module-level and defined once, which is why this is a footnote rather than a defect — but it is the same problem stage 4's staleness question (§12) faces in a harder form, and the two should be solved with one idea if either is.

### Types, not constraints

`typing-validation` answers *"is this value an `int`"*, never *"is this value positive"*. Whether that holds forever is deliberately open — [TYPES.md](TYPES.md) keeps `Annotated` metadata identity-bearing precisely so the door stays usable — but nothing in 2.0 walks through it, and no release promises to.

### Not a coercion library

It inspects and reports. It never converts, parses, serialises or repairs. A value is valid or it is not; making it valid is the caller's business.

### Python 3.14 and above

No back-compatibility, ever, in this major version. §1 lists what that deletes; the list is long enough to justify the floor on its own.

### Zero runtime dependencies

Part of the contract, not a preference — §8 shows what happens when a library at the bottom of the stack forgets it.

## 14. Open questions

### ~~The `diagnose` message format~~ — settled

Chosen as this section asked: four complete families, each rendered over the same spread of cases, rather than cherry-picked examples. What shipped is three slots — what was expected, `at:` where, `in:` what — with the third dropped when the first has already named the type:

```
expected int, got str '1975'
  at:  value.year
  in:  Movie
```

Two rules find the place to report, and the naive walk gets both wrong: through a union, follow the member that got furthest; and report the type recorded at the deepest step rather than whatever the walk bottoms out in. See `diagnosis.py`.

Messages are also safe against the objects they describe. Every value and type in one is caller-supplied and may raise from its own `__repr__` or `__str__` — a class that reprs its attributes does exactly that from inside `__init__`, which is where a caller validating `self` meets it. Rendering such a failure used to re-raise, replacing the diagnosis with a traceback into the caller's own code, so `_display.py` guards every one of those calls and names what refused rather than propagating it.

### Staleness detection for the persistent cache

**The hardest problem left in the design, and the reason §12 puts marshalling last.**

There is no answer yet — only the requirement that a stale entry must be *detected*, never trusted, because a silently-wrong cached validator is the worst failure this library could have. §13's "types are immutable once used" is the same question in an easier setting, and the two probably want one idea.

### ~~The inlining budget~~ — settled

Resolved during stage 3 on §11's evidence, as this section asked, and the evidence contradicted the premise. There is no cliff to tune around: cost is linear in emitted size and unrolling always repays, within about one value for `list[int]` and four hundred and sixty-five for a forty-field `TypedDict`. So the budget is a guard rail against a monstrous type stalling the compiler by surprise, not a tuning knob. §3.4 carries the two traps — it must count nodes *with multiplicity*, and nesting is a second dimension no node budget can see.

A gate that would fall back to §3.3 when little was worth unrolling was built afterwards, measured and **rejected**: it saved only build time, which is one-time and cached, and the inlinable share does not predict whether compiling helps.

### ~~The `TypeStructure` API~~ — settled

`inspect_type` returns the interned `TypeNode` itself. It carries the type it was built from, its form (an enum mirroring the catalogue), its children, labels for those children where they have names, whether it is supported, and why not when it is not. `unsupported_components()` names the culprits and `walk()` enumerates the graph, terminating on cycles.

There is no separate artifact, for the reason in §3.5: §4's whole claim is that this is *one* class, and a mirror of it could only drift.

Two shape decisions worth recording, because both are judgement calls:

- **A `Literal` has no children.** Its arguments are values, not types.
- **A generic class has no children, but a plugin-backed one has all its arguments as children.** A child is a component that bears on the verdict, and an unclaimed generic class's arguments explicitly do not (§7). A plugin's do, and totality must propagate through them — `NDArray[np.uint8 | np.float32]` has a union inside it that the core validates.

### The cache-management spelling

Settled provisionally as `clear_cache()`, `forget_type(t)` and a `scoped_cache()` context manager. The shape was agreed in §4.3; these are just names, and nothing depends on them.

### Smaller, deferred by agreement

- **Plugin-contributed manifest entries** (§7). Ours-alone is simpler; nothing forecloses opening it.
- **The configuration surface** (§8). Settled for 2.0 by finding it empty: implementing discovered no options, so no manager ships. Still empty after stage 3, which shipped no switch of its own — §3.4's inlining budget was the candidate, and turned out to be a guard rail rather than something to tune.
