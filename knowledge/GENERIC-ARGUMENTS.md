# Generic arguments at runtime

`validate(Box("hi"), Box[int])` returns `True`, and [TYPES.md](TYPES.md) says that is correct: a generic class validates on **its origin alone**.
This document is why that is the default, why the default is not good enough, and what `__validate__` is a candidate for.

It is a *positioning* document rather than a specification.
`TYPES.md` remains the authority on what validation means; nothing here changes it.

---

## 1. The gap, precisely

Two facts, and the gap is the space between them.

**The alias knows its arguments.** `Box[int]` retains `__args__ == (int,)`. Nothing is erased there — PEP 585 says so in as many words, under *Generics erasure*: preserving the generic type at runtime "enables runtime introspection of the type which can be used for API generation or runtime type checking. Such usage is already present in the wild."

**The instance does not.** `Box("hi")` records nothing about `T`. That is erasure, and it is deliberate: PEP 483 states flatly that "all type information in instances is erased at runtime", and PEP 484 names it — "the runtime class of the objects created by instantiating them doesn't record the distinction".

So `validate(val, Box[int])` can see `int`. What it cannot see is what `val`'s `T` was. The two ends exist and nothing joins them — and the only party that could join them is the class, which knows what it did with the argument it was handed.

**That is the whole of what `__validate__` is for.** It is not a way to recover erased information. It is a way for a class to say what its arguments *mean* about its values, since nothing else can.

---

## 2. What the record says, and the folklore it corrects

The usual explanation for `isinstance(x, list[int])` raising `TypeError` is that generics are erased, so the check is impossible.
**That is not the recorded reason, and believing it leads to the wrong design.**
Erasure explains why `type(x)` cannot tell you; it does not explain the `TypeError`, because `list[int]` retains `__args__` and a checker could walk the *value*. Three reasons are on the record, and none of them is erasure.

**A shallow check that looks deep is worse than no check.**
Mark Shannon, in an email Guido pasted into [python/typing#136](https://github.com/python/typing/issues/136#issuecomment-104700131) on 2015-05-22 — the comment that got `__instancecheck__` and `__subclasscheck__` deleted:

> For example,
> List[int] and List[str] and mutually incompatible types, yet
> isinstance([], List[int]) and isinstance([], List[str))
> both return true.
>
> Just delete all the `__instancecheck__` and `__subclasscheck__` methods and I'll be happy.

Note what he is objecting to. In 2015 the check *did not raise* — it returned `True`, permissively, on the origin alone. The `TypeError` exists because the permissive answer was judged a false promise.

**A deep check was ruled out of scope, not undesirable.**
[PEP 585](https://peps.python.org/pep-0585/#making-isinstance-obj-list-str-perform-a-runtime-type-check), *Making `isinstance(obj, list[str])` perform a runtime type check*:

> This functionality requires iterating over the collection which is a destructive operation in some of them. This functionality **would have been useful**, however implementing the type checker within Python that would deal with complex types, nested type checking, type variables, string forward references, and so on is out of scope for this PEP.

And the adjacent section rejects the shallow check for Shannon's reason, restated four years later: `isinstance([1, 2, 3], list[str])` returning `True` would be "surprising".

**The runtime must not out-promise the static checker.**
PEP 544 refuses subscripted protocols because "a reliable answer could not be given at runtime in this case".

**The split was deliberate, and this library is the far side of it.**
CPython shipped the primitives — `get_origin`, `get_args` — and declined the checker, keeping `__args__` alive *specifically* so that libraries could do this.
Guido, in the same 2015 thread ([#136](https://github.com/python/typing/issues/136#issuecomment-138174590)), replying to the author of typeguard, who had asked how he was supposed to build a runtime checker with the checks gone:

> The idea is that you would have to write your own functions similar to `isinstance()` and `issubclass()` to introspect the objects created at run-time by type annotations. You are right however that the introspection interface has not yet been specified -- **I think it would have to be a separate PEP.**

That PEP was never written. Guido even named its functions — `is_consistent_with()` for the `issubclass` equivalent, `is_acceptable_for()` for the `isinstance` one — and said he planned "to ask others to contribute such functions". A decade of maintainer verdicts has said the same thing since: *write your own implementation*, and return a `TypeGuard`.

**So the ground `typing-validation` stands on is not neglected ground. It is assigned ground.**
What was never assigned to anyone is the part this document is about: what a *user's own* generic should do.

---

## 3. Why the obvious mechanisms do not work

**`__orig_class__` is not it.** CPython's `typing._GenericAlias.__call__` does set it:

```python
result = self.__origin__(*args, **kwargs)
try:
    result.__orig_class__ = self
except Exception:
    pass
```

but it is set only by the Python `_GenericAlias`, never by the C `GenericAlias`, so `list[int]()` has none; it lands *after* `__init__`, so the constructor cannot see it; it is absent entirely for `Box("hi")`, which is how almost everyone constructs; and it is explicitly not API — Levkivskyi, [#519](https://github.com/python/typing/issues/519): "this is however **not an official API**", and again in #658: "undocumented internal attribute that you are using **totally at your own risk**".
Guido considered making the C `GenericAlias` set it and declined on memory cost, adding "the purpose of `__orig_class__` is questionable -- why have it at all?"

The deeper objection is Lehtosalo's, from [#79](https://github.com/python/typing/issues/79#issuecomment-93891773) in 2015, and it is the one that forecloses the whole family of instance-recording schemes:

> the information about type arguments is only partial and thus **can't be usefully relied on** … If an instance is created using `Node(...)`, the type argument value is missing. Again, this means that runtime introspection of type argument values is not very useful since **the value is not always there, and the behavior is inconsistent**.

**A hook, then.** If the instance cannot carry the argument and the runtime will not check it, the only remaining party is the class.

---

## 4. What the ecosystem does

Every library measured in [`benchmark/PEER-COMPARISON.md`](../benchmark/PEER-COMPARISON.md) either answers on the origin alone or refuses the type. On `Box("hi")` against `Box[int]`:

| library           | answer                                 |
|:------------------|:---------------------------------------|
| typing-validation | `True` — origin-only, per `TYPES.md`   |
| beartype          | `True` — agrees                        |
| typeguard         | `True` — agrees                        |
| trycast           | raises `TypeNotSupportedError`         |
| pydantic          | raises `PydanticSchemaGenerationError` |

None offers a route from origin-only to argument-checked.
Several offer hooks for *adjacent* jobs, and their naming is the relevant precedent:

| library  | hook                                                           | shape                                                         |
|:---------|:---------------------------------------------------------------|:--------------------------------------------------------------|
| pydantic | `__get_pydantic_core_schema__`, `__get_pydantic_json_schema__` | returns a *schema*, not a verdict — build-time, not call-time |
| beartype | `__beartype__`, `__beartype_hint__`                            | namespaced throughout                                         |
| cattrs   | `register_structure_hook(cls, fn)`                             | no dunder at all — registration API                           |
| msgspec  | none                                                           | —                                                             |

Two things follow. Every hook in the field is **namespaced** or is not a dunder. And pydantic's is the closest in spirit but differs in kind: it returns a schema the library then compiles, where `__validate__` returns a verdict the library trusts.

**Prior art for the exact shape: one forum post, and no PEP.**
A search of all PEPs finds no proposal for a validation dunder of any name.
The only proposal found anywhere is a [2024 thread on discuss.python.org](https://discuss.python.org/t/runtime-type-checking-using-parameterized-types/70173) by Yuxuan Zhang, proposing "a new hook method `__type_check__` and a builtin function `type_check()` that calls `__type_check__`" — the same idea, one dunder over. No core developer replied to it; a participant answered by quoting PEP 585's out-of-scope paragraph back at it, and the author shipped a library instead. Its author's postscript is worth recording: "I expected to find a lot of similar proposals or discussions, but somehow I did not find any similar proposal out there."

So this is not a crowded field. It is an empty one, which is a reason for caution as much as for confidence.

---

## 5. `__validate__`, and the case against it

```python
class Box[T]:
    @classmethod
    def __validate__(cls, val: Any, args: tuple[Any, ...]) -> bool:
        return is_valid(val.item, args[0])
```

The class receives the value and the alias's arguments, and answers.
It is call-time rather than build-time, it returns a verdict rather than a schema, and it composes: `Checked[Tree]`, `Checked[NDArray[np.uint8]]` and `Checked[Checked[int]]` all work because the hook calls back into `is_valid`.

**The strongest objection is the name, and it is sourced.**
Guido, in the very thread that assigned this work to third parties ([#136](https://github.com/python/typing/issues/136#issuecomment-138174590)):

> non-stdlib code should never use dunder names for anything other than their documented meaning, as the stdlib can at any point define a new dunder name without any concern for existing occurrences of that dunder name in user code. So non-stdlib code that uses `__extra__` is already broken.

`__validate__` is exactly that: non-stdlib code claiming an undocumented dunder, on a name generic enough that the stdlib might plausibly want it. That is presumably why pydantic and beartype both namespaced, and why cattrs uses no dunder at all.
**A namespaced name should be the default and the bare one should carry the burden of proof.** The library already ships `register_validator(cls, check)` for classes one does not own, which is cattrs' answer and needs no dunder at all; the dunder's advantage is only that it travels with the class.

**The second objection is Shannon's, turned around.** He deleted a check because a shallow answer masqueraded as a deep one. `validate(Box("hi"), Box[int]) → True` is a shallow answer to a deep question — the same shape he objected to. The defence is that the alternative is refusing the type (as trycast and pydantic do), and that the permissive answer is the one beartype and typeguard also give; but "everyone else does it" is not the argument `TYPES.md` currently makes, and the tension is real enough to be worth stating rather than resolving by assertion.

**The third is scope.** PEP 585 declined the deep check partly because "iterating over the collection … is a destructive operation in some of them". This library has an answer to that specific objection — `validated_iter` checks items on the way past rather than eagerly, because consuming a one-shot iterator to inspect it destroys the value — and that answer is worth putting into the record, since the objection is one of only two substantive ones a PEP ever gave.

---

## 6. If this were to be proposed

Not a plan; the shape a plan would need.

- **Namespace the dunder first**, or be able to say why not. This is the cheapest thing on the list and the only one with a BDFL quote against the status quo.
- **The proposal is not "make `isinstance` work".** That has been refused three times on stable grounds, and refusing it again is not interesting. The proposal is the *interface* Guido said "would have to be a separate PEP" and nobody wrote — with a hook for the one case the runtime provably cannot answer.
- **Align the return with what maintainers have prescribed for a decade.** Eric Traut, [#1257](https://github.com/python/typing/issues/1257): "If you want to apply different semantics (e.g. perform deeper nested checks), you can write your own implementation. If you use `TypeGuard` as a return type, then a static type checker will also be able to use it for type narrowing." Whether `is_valid` should return `TypeIs[T]` is a question this library can answer on its own, and probably should before asking anyone anything.
- **Bring the destructive-iteration answer**, since PEP 585 named it and `validated_iter` addresses it.
- **Expect the audience to be small.** The 2024 thread drew no core developer. The measurement to bring is not "we are fast", it is that the corpus contains both `Box` (bare) and `Checked` (declaring), and that the difference between them is the only thing in the field that closes this gap.

---

## 7. Sources

Every quotation above was fetched from its primary source rather than recalled.

- Shannon's objection, quoted by Guido: [python/typing#136 (comment)](https://github.com/python/typing/issues/136#issuecomment-104700131), 2015-05-22.
- Guido on dunder names and the missing PEP: [python/typing#136 (comment)](https://github.com/python/typing/issues/136#issuecomment-138174590), 2015-09-07.
- Lehtosalo on instances not usefully carrying arguments: [python/typing#79 (comment)](https://github.com/python/typing/issues/79#issuecomment-93891773), 2015-04-17.
- `__orig_class__` is not API: [python/typing#519](https://github.com/python/typing/issues/519), [#658](https://github.com/python/typing/issues/658).
- Shallow check "surprising"; deep check "would have been useful … out of scope"; `__args__` kept for checkers "already present in the wild": [PEP 585](https://peps.python.org/pep-0585/).
- Erasure as design: [PEP 483](https://peps.python.org/pep-0483/), [PEP 484](https://peps.python.org/pep-0484/#instantiating-generic-classes-and-type-erasure).
- Subscripted protocols cannot be answered reliably: [PEP 544](https://peps.python.org/pep-0544/).
- "Write your own implementation … use `TypeGuard`": [python/typing#1257](https://github.com/python/typing/issues/1257).
- The one dunder proposal: [discuss.python.org, "Runtime type checking using parameterized types"](https://discuss.python.org/t/runtime-type-checking-using-parameterized-types/70173), 2024-11-04.
