# Type Support

This document is the catalogue of type forms that `typing-validation` understands: for each form, what validation checks, what it deliberately does not check, and why.

It is the *conceptual* specification that every validation mechanism implements.
The mechanisms — `validate`, `validator`, `compiled_validator`, `inspect_type` and `diagnose` — share no implementation code with one another by design, so this catalogue is the only thing binding them to a common meaning.
Where they disagree, this document is right and the code is wrong.

`DESIGN.md` covers the machinery: how the mechanisms are built and how they relate.
This document covers only *what is supported and what it means*, so that the type surface can be revised without touching the architecture.

## How to read this document

Each entry has a **status**:

- **Supported** — validated as described.
- **Supported via plugin** — validated only once the relevant extension is imported; unsupported otherwise.
- **Unsupported** — raises `UnsupportedTypeError`, and poisons any type containing it (see [Totality](#totality)).

Each entry also carries a **provenance**, relative to v1:

- **v1 parity** — behaves as v1 did.
- **changed** — deliberately differs from v1; every one of these is listed under [Deviations from v1](#deviations-from-v1).
- **new** — not supported in v1.
- **dropped** — supported in v1, deliberately removed.

Where an entry does not check something, the omission is tagged with its reason:

- `[impossible]` — the information does not exist at runtime; no implementation could check it.
- `[by design]` — we could check it and deliberately do not.
- `[deferred]` — we intend to check it, but not in 2.0.

The distinction matters. An `[impossible]` limit is permanent and must be documented to users, because they will otherwise assume the check is happening. A `[by design]` limit is a decision we own and can revisit. A `[deferred]` limit is a promise.

## Global rules

### Totality

Validation support is all-or-nothing: **if any component of a type is unsupported, the whole type is unsupported.**

`tuple[int, Callable[[int], int]]` is unsupported in its entirety, even though the `int` component is perfectly checkable.
There is no partial mode in which the supported parts are checked and the rest waved through, because a validation that silently skips part of its obligation is worse than no validation — it reports success it has not earned.

This rule is the entire reason `can_validate` exists: it lets a caller ask, up front, whether `validate` would be able to honour a type at all.

An unsupported component therefore poisons every type that contains it, transitively.
`inspect_type` still reports the *whole* structure and marks precisely which component caused the poisoning, so "unsupported" is always actionable rather than opaque.

### Purity

**Validation never mutates or consumes the value it inspects.**

This is not a stylistic preference; three separate parts of the design rest on it.
Union members must be tried one after another, and a member that fails part-way must leave nothing behind for the next member to trip over.
`validate` and the compiled validators must agree on every input, which they cannot do if the act of checking changes what is being checked.
And a caller must be able to validate a value and then still use it.

The forms that cannot honour purity are exactly the forms that need special treatment: a one-shot iterator cannot be inspected without being consumed. See [Iterators and iterables](#iterators-and-iterables).

## Catalogue

### Basic types

**Supported** · *v1 parity*

`bool`, `int`, `float`, `complex`, `bytes`, `bytearray`, `memoryview`, `str`, `range`, `slice`.

**Checks:** `isinstance(val, t)`.

Normal Python subclass semantics apply and are not special-cased.
`validate(True, int)` succeeds because `bool` is a subclass of `int`; `validate(1, bool)` fails.
This is deliberate: the runtime type lattice is the one we validate against, and second-guessing it would surprise more people than it helped.

### `None` and `NoneType`

**Supported** · *v1 parity*

**Checks:** `val is None`. Both the `None` spelling and `types.NoneType` are accepted as the type.

### `Any`

**Supported** · *v1 parity*

**Checks:** nothing; every value is valid.

### Bare collection, mapping and tuple types

**Supported** · *v1 parity*

The unparametrised forms: `list`, `tuple`, `set`, `frozenset`, `dict`, `collections.deque`, `collections.defaultdict`, and the abstract base classes `Collection`, `Set`, `MutableSet`, `Sequence`, `MutableSequence`, `Iterable`, `Iterator`, `Container`, `Mapping`, `MutableMapping`, `Hashable`, `Sized`, `Buffer`.

**Checks:** `isinstance(val, t)` against the runtime class or ABC.

The deprecated `typing` aliases (`typing.List`, `typing.Dict`, `typing.Deque`, …) are accepted and mean exactly their builtin or `collections.abc` counterparts.
`typing.ByteString` still exists in 3.14 and is accepted, mapping to `collections.abc.Buffer`.

### Parametric collections

**Supported** · *v1 parity*

`list[T]`, `set[T]`, `frozenset[T]`, `deque[T]`, `Collection[T]`, `Set[T]`, `MutableSet[T]`, `Sequence[T]`, `MutableSequence[T]`.

**Checks:** `isinstance(val, origin)`, then every item against `T`.

Failures report the index of the offending item.
For unordered collections the index is a position in iteration order and is **not stable across runs**; `diagnose` marks it as such rather than implying an addressable location.

### Parametric mappings

**Supported** · *v1 parity*

`dict[K, V]`, `defaultdict[K, V]`, `Mapping[K, V]`, `MutableMapping[K, V]`.

**Checks:** `isinstance(val, origin)`, then every key against `K` and every value against `V`.

### Tuples

**Supported** · *v1 parity*

**Fixed-length** `tuple[X, Y, Z]` checks the length, then each item against its positional type.
**Variadic** `tuple[X, ...]` checks every item against `X`.
**Empty** `tuple[()]` checks that the value is an empty tuple.

### Unions

**Supported** · *v1 parity*

`Union[X, Y]`, `X | Y`, and `Optional[X]` — which are, in 3.14, all the same thing.

**Checks:** the value is valid for **at least one** member.

Member order does not affect the outcome, only the order in which a failure lists the members it tried.
Python normalises unions before we ever see them: nested unions are flattened, duplicates collapse, `Union[X]` degenerates to `X`, and `Optional[X]` is `X | None`.

3.14 merged `types.UnionType` into `typing.Union`, so both spellings produce the same object and there is no surface distinction left to preserve. v1's `use_UnionType` tracking has nothing to track.

### Literals

**Supported** · **changed**

`Literal[...]` with `int`, `bool`, `str`, `bytes`, `None` and `Enum` members.

**Checks:** the value is one of the listed literals, matched by **type and equality**, or by identity for enum members and `None`.

v1 tested `val in t.__args__`, which is bare `==` and therefore wrong: `validate(True, Literal[1])` and `validate(1.0, Literal[1])` both *pass* in v1, because `True == 1` and `1.0 == 1`.
PEP 586 is explicit that a literal's type is part of its identity, so v2 requires the type to match.

See [Deviations from v1](#deviations-from-v1).

### Type variables

**Supported** · **changed**

**Checks:** the value against the type variable's bound, if it has one; or against its constraints, if it has those instead. A type variable with neither accepts every value.

A constrained type variable — `TypeVar("T", int, str)` — is semantically the union of its constraints, and validates as that union. A type variable has either a bound or constraints, never both, so the two rules never collide.

v1 ignored constraints silently, so `validate(1.5, T)` passed for a `T` constrained to `int` and `str`. That was a gap rather than a decision: unions are already a supported form, so honouring constraints needs no new machinery.

**Does not check:** variance — `[impossible]`. Variance constrains how a generic *type* may be substituted, not what a *value* may be; no property of a value could witness it.

### `TypedDict`

**Supported** · **changed**

**Checks:** the value is a mapping with string keys; every required key is present; every key that is present and annotated has a value valid for its annotation.

**Does not check:**
- Extra keys not named in the annotations — `[impossible]` in 3.14. PEP 728's `closed=True` and `__extra_items__` would make this expressible, but 3.14's `TypedDict` rejects the `closed` keyword outright, and we take no `typing_extensions` dependency. Revisit when the language supports it.
- That the value is *actually* a `TypedDict` instance — `[impossible]`. `TypedDict` has no runtime identity; any conforming mapping is indistinguishable from one.

`Required[X]`, `NotRequired[X]` and `ReadOnly[X]` qualifiers are recognised and stripped.
Requiredness is taken from `__required_keys__` / `__optional_keys__` rather than re-derived from the annotations.
`ReadOnly` has **no runtime meaning** — it constrains assignment, not value shape — so `ReadOnly[X]` validates exactly as `X`. It is recognised so that it does not read as an unsupported type; `__readonly_keys__` is available and reported by `inspect_type`, but never affects a verdict.

The *changed* status is a consequence of the machinery: v1 read annotations with `get_type_hints`, which strips the three qualifiers for us. v2 reads them via `annotationlib`, which does not — so v2 handles them explicitly. The observable behaviour is unchanged; the obligation is new. See `DESIGN.md` §6.

### `NamedTuple`

**Supported** · **changed**

Two forms, with different meanings.

**Bare `typing.NamedTuple`** means *"any named tuple instance"*. Type checkers enforce exactly that: mypy accepts instances of `NamedTuple` subclasses and of `collections.namedtuple` classes, and rejects plain tuples, ints and strings. This library exists to enforce at runtime what type checkers enforce statically, so the form is honoured.

**Checks:** `isinstance(val, tuple)`, and that `type(val)` has a `_fields` attribute.

**Does not check:** that the class was genuinely produced by `NamedTuple` or `collections.namedtuple` — `[impossible]`. There is no nominal marker to check: `Pt.__mro__` is `(Pt, tuple, object)`, and `NamedTuple` never appears in it, because `typing.NamedTuple` is a *function* rather than a class. The structural probe is the only runtime witness, so a hand-written `tuple` subclass defining `_fields` is indistinguishable from a real named tuple. It nevertheless agrees with the type checker on every case above.

**A concrete subclass** — `class Pt(NamedTuple): x: int; y: int` — is an ordinary class: it checks `isinstance(val, Pt)`, then each field against its annotation.

Field validation makes `NamedTuple` subclasses the one class form whose contents are checked, a deliberate exception to the rule for [generic classes](#generic-classes). It is justified because the information is genuinely available and nowhere else is: field types are recorded in `__annotations__`, the value is a tuple so fields are positionally addressable, and the check is pure and cheap. A generic class exposes no equivalent.

v1 got both forms wrong. Bare `typing.NamedTuple` was listed as a validatable pseudotype despite not being isinstance-able, so `validate(p, typing.NamedTuple)` raised a raw `TypeError: isinstance() arg 2 must be a type…` — indistinguishable, to a caller catching `TypeError`, from a validation failure — and `is_valid(p, typing.NamedTuple)` crashed with `AttributeError`, because it assumes every `TypeError` it catches carries a `validation_failure`. Subclass fields went unchecked.

**`collections.namedtuple` is dropped.** v1 listed it beside the forms above, but it is a *factory function*: `x: collections.namedtuple` is not an annotation anyone writes, and `isinstance` against it can only raise. Its presence is what marks v1's set as an enumeration of tuple-ish names rather than a list of validation targets.

### `Type[T]` and `type`

**Supported** · *v1 parity*

**Checks:** the value is a class, and is a subclass of `T`. `T` may be a class, a union of classes, or `Any` (which accepts any class).

Bare `type` and bare `typing.Type` check only that the value is a class.

**Does not check:** subtype relationships for anything other than classes and unions of classes — `[by design]`. `Type[list[int]]` and similar are unsupported: `issubclass` cannot express them, and inventing a bespoke subtype relation is out of scope.

### Protocols

**Supported** · *v1 parity*

**Checks:** `isinstance(val, t)`, for protocols decorated `@runtime_checkable` only.

A non-runtime-checkable `Protocol` is **unsupported**, because `isinstance` against it raises.

**Does not check:** method signatures — `[impossible]`. `runtime_checkable` verifies the *presence* of members, not their types. A value can satisfy a runtime protocol check and still be unusable through it. This is a limit of the language, and users consistently expect otherwise, so it must be documented loudly.

### Generic classes

**Supported** · *v1 parity*, with an extension route

**Checks:** `isinstance(val, origin)`.

**Does not check:** the type arguments — `[by design]`, escapable. `validate(Box(), Box[int])` succeeds regardless of what the box contains, because a generic class does not, in general, expose enough at runtime to determine its arguments.

This is where v1 stopped, with a TODO proposing a dunder classmethod. v2 delivers it: a class can declare how its type arguments are validated, and third-party classes can be handled by registration. See [Plugin-provided types](#plugin-provided-types) and `DESIGN.md` §7.

Absent such a declaration, the arguments remain unchecked and the class validates on its origin alone. It is *not* an error to parametrise a class we cannot introspect.

### Type aliases

**Supported** · **new**

PEP 695 aliases: `type JSON = int | str | list[JSON] | dict[str, JSON]`.

**Checks:** the value against the alias's `__value__`.

Aliases are lazily evaluated and resolve against their defining module, so they need no help from the caller.
They may be recursive, and recursion through an alias is fully supported: an alias is the natural point at which a cycle closes.

Aliases are *not* transparent. `type MyInt = int` is a distinct type from `int` and keeps its own identity, so failures report `MyInt` rather than silently reporting `int`.

Generic aliases (`type Pair[T] = tuple[T, T]`) are supported through substitution.

### Forward references

**Supported when annotation-derived**, otherwise **unsupported** · **changed**

A forward reference is resolvable **iff it came from an annotation**, because that is what identifies the class it belongs to — and the class is what identifies the module to resolve against.

The reference itself is not what carries that information, and usually does not carry it at all. Only a *top-level* `TypedDict` annotation records a module on its reference. A `NamedTuple` records none even at top level, and a reference nested inside a generic degrades to a bare string, which has nowhere to record one:

| Written | Recorded as |
|---|---|
| `class TD(TypedDict): x: "Later"` | `ForwardRef('Later', module='mymod')` |
| `class NT(NamedTuple): x: "Later"` | `ForwardRef('Later')` — no module |
| `class TD(TypedDict): x: list["Later"]` | `list['Later']` — a bare string |

**All three are supported**, because in all three the owning class is known, and resolution asks *it* for the module. That is uniform, and for the latter two it is the only thing that works.

A reference written inline in a call — `validate(x, list["JSON"])` — has **no owner**, and is therefore **unsupported**. That, and not any property of the reference, is what makes it unresolvable: `list["JSON"]` written inline and `list["JSON"]` written as an annotation record the *identical* bare string, and only the second one can be resolved.

v1 papered over the inline case with the `validation_aliases` context manager, which v2 **drops**. The replacement is a PEP 695 alias, and the error message says so.

The reason is not tidiness. The only way to resolve an inline reference is against the caller's frame — but validators are cached and interned, so a node for `list["JSON"]` would then resolve differently depending on which caller happened to build it first. That would make interning semantically observable, which `DESIGN.md` §4 forbids outright. It is also incoherent for `validator(t)`, which is called from somewhere entirely unrelated to where `t` was written.

An annotation-derived reference that cannot be resolved is reported precisely — naming the field and the unresolved name — rather than leaking a bare `NameError`, as v1 did.

### `Annotated`

**Supported** · **new**

**Checks:** the value against the underlying type. `Annotated[int, "positive"]` validates exactly as `int`.

**Does not check:** the metadata — `[by design]`.

`Annotated` is **not** stripped. `Annotated[int, Ge(0)]` is a distinct type from `int`, with its own identity and its own cache entry, and failures report the annotation as written.

This costs some deduplication and buys two things. Error messages tell the truth about the type the user wrote. And metadata is identity-bearing from day one, so a future release *could* act on it — the modern idiom for `Annotated` is precisely to carry validation constraints, and users who write `Annotated[int, Ge(0)]` tend to expect it enforced. Stripping it now would foreclose that, or force a cache-key change later.

To be unambiguous: **acting on metadata is not on the roadmap, and not ruled out either.** *We validate types, not constraints* is the position for now rather than a permanent commitment. The door is held open because holding it open is free; no release promises to walk through it.

One consequence worth stating: metadata participates in the type's hash, so `Annotated[int, {"ge": 0}]` is **unhashable**. That does not make it unsupported. Interning is an optimisation and must never be observable, so an unhashable type simply skips the cache. See `DESIGN.md` §4.1.

### `NewType`

**Supported** · **new**

**Checks:** the value against `__supertype__`. `validate(5, UserId)` where `UserId = NewType("UserId", int)` checks that the value is an `int`.

**Does not check:** anything distinguishing a `UserId` from a plain `int` — `[impossible]`. `NewType`'s constructor is the identity function and `isinstance` against it raises. There is no runtime witness of the distinction, so the supertype is the strongest check that exists.

This means the check is **vacuous beyond the supertype**, and validation here is strictly weaker than static typing. Users will assume otherwise. Documented loudly for that reason.

The type is not stripped: failures report `UserId`, not `int`.

### Iterators and iterables

This is where [purity](#purity) bites, and the rules differ per form.

**`Iterator[T]` — Supported** · *v1 parity*

**Checks:** `isinstance(val, Iterator)`.

**Does not check:** the item type — `[impossible]` without violating purity. Determining the items of a one-shot iterator consumes it, leaving the caller with an exhausted object. The `validated_iter` function exists exactly for this: it wraps the iterator so each item is checked as it is yielded, which is the only honest way to do it.

**`Iterable[T]` — Supported** · **changed**

**Checks:** `isinstance(val, Iterable)`, and — when the value is also a `Collection` — every item against `T`.

A `Collection` can be iterated repeatedly and sized without being consumed, so checking its items is safe. When the value is *not* a `Collection` it is potentially one-shot, and the item type goes unchecked for the same reason as `Iterator[T]`.

v1 intended exactly this (its `_maybe_collection_pseudotypes` table lists `Iterable` alongside `Container` for this purpose) but never did it: `abc.Iterable` appears in both that table and the iterator table, and the iterator arm is tested first, making the `Iterable` arm **unreachable dead code**. The visible symptom is an inconsistency — given `[1, "a"]`, a list and hence a `Collection`, v1 fails `Collection[int]`, `Sequence[int]` and `Container[int]` but *passes* `Iterable[int]`.

**`Container[T]` — Supported** · *v1 parity*

**Checks:** `isinstance(val, Container)`, and — when the value is also a `Collection` — every item against `T`. Same rule as `Iterable[T]`; v1 already did this correctly.

### Plugin-provided types

**Supported via plugin** · **new**

Types whose validation is supplied by an extension rather than by the core.
The hook is the generic-class dispatch point: precisely where the core has run out of things it can determine on its own.

A plugin must be **imported explicitly**. Without the import, its types are `UnsupportedTypeError`, and the error names the import that would enable them.

The alternative — auto-enabling when the underlying library happens to be present — was rejected because it makes the supported surface depend on transitive imports: `can_validate(NDArray[np.uint8])` would answer differently depending on whether some unrelated dependency had imported numpy. A predicate people branch on must not behave that way.

**NumPy** is the first plugin and ships in this distribution as `typing_validation.numpy`. It provides `NDArray[dtype]` and `ndarray[shape, dtype]`, checking the array's dtype (including unions of dtypes and `Any`) and its shape. This is v1 functionality, moved out of the core: v1 wired an `import numpy` probe into the middle of the dispatcher, which put an optional third-party dependency on the hot path.

See `DESIGN.md` §7 for the plugin protocol and its costs.

## Not supported

Each of these raises `UnsupportedTypeError` and poisons any type containing it.

| Form | Why |
|---|---|
| `Callable[...]` | `[deferred]`. Callability is checkable; signatures are not, in general. v1 carried a half-written implementation in comments for years, which is its own verdict. Checking only `callable(val)` while ignoring the signature would be a totality violation dressed as support. |
| `ParamSpec`, `Concatenate` | `[deferred]`. Only meaningful for `Callable`, so they follow it. |
| `TypeGuard`, `TypeIs` | `[impossible]` as value types. They describe a *function's* return contract, not a property of a value. |
| `Self` | `[deferred]`. Only meaningful relative to an enclosing class context, which `validate(val, t)` does not have. |
| Non-runtime-checkable `Protocol` | `[impossible]`. `isinstance` against it raises. |
| Inline forward references | See [Forward references](#forward-references). |
| `collections.namedtuple` | `[impossible]`. A factory function, not a type; `isinstance` against it can only raise. Never a valid annotation. See [`NamedTuple`](#namedtuple). |
| PEP 728 `closed` / `__extra_items__` | `[impossible]` in 3.14; the language does not have it yet. |

## Deviations from v1

Behaviour that v2 deliberately changes. Each is a bug fix or a forced consequence, not a preference.

| Change | Rationale |
|---|---|
| `Literal[1]` no longer accepts `True` or `1.0` | v1 used bare `==`. PEP 586 makes the literal's type part of its identity. |
| `Iterable[T]` now checks items when the value is a `Collection` | v1 intended this; a dispatch-order bug made the code unreachable. Removes an inconsistency with `Container[T]`. |
| Constrained `TypeVar`s are checked against their constraints | v1 ignored them, so `validate(1.5, T)` passed for a `T` constrained to `int` and `str`. |
| Bare `typing.NamedTuple` is supported structurally | v1 leaked a raw `isinstance` TypeError and crashed `is_valid` with `AttributeError`. Type checkers enforce the form, so it is honoured rather than refused. |
| `NamedTuple` subclasses have their fields validated | v1 checked only `isinstance`. The field types are available and the check is pure. |
| `collections.namedtuple` is no longer a validation target | A factory function, not a type. |
| `validation_aliases` removed; inline forward refs unsupported | Replaced by PEP 695 aliases. Caller-frame resolution is incompatible with interning. |
| NumPy support requires `import typing_validation.numpy` | Keeps the supported surface independent of transitive imports, and an optional dependency off the hot path. |
| `Annotated`, `NewType` and aliases are no longer invisible | They are distinct types and are reported as written. v1 did not support them at all. |
| Unresolvable annotation references report precisely | v1 leaked `NameError` from inside `validate`. |

## Open questions

None currently open.

Three questions previously recorded here are settled and folded into the catalogue above: `NamedTuple` subclasses do have their fields validated, constrained type variables are checked against their constraints, and acting on `Annotated` metadata is neither promised nor ruled out.
