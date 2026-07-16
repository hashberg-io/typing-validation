# Peer comparison

A comparative review of `typing-validation` v2.2.0 against ten runtime type-checking and validation libraries, over 55 cases on Python 3.14.4.

This document is written, not generated.
It quotes as few figures as it can, and every one it quotes comes from [`REPORT.md`](REPORT.md), which is regenerated from the suite and is the authority.
This is the synthesis and the judgement; where the two disagree, `REPORT.md` is right.

**Every number here is from one machine.**
Ratios between a pure-Python validator and a compiled core move with the hardware, and at least one conclusion below changed sign when the suite was re-run on a different one.
Where a claim is that close, it says so rather than reporting whichever run flattered us.

---

## 1. Summary

**typing-validation answers every case in the corpus, and it is the only library measured that reaches all of them.**
That is a claim about *reach*, and it is the honest one.
It is not a claim that the rest of the field is wrong: on the type forms the whole field supports, typeguard configured to check every item is also correct on every case, and pydantic in strict mode misses only NumPy.

|                                        |                                                                                                   |
|:---------------------------------------|:--------------------------------------------------------------------------------------------------|
| **Reach**                              | the only library that checks a generic's arguments or a NumPy dtype — 17 of 55 cases, alone       |
| **Agreement, shared surface**          | 100% — tied with typeguard (`ALL_ITEMS`); pydantic 95%, trycast 89%                               |
| **vs typeguard** (`ALL_ITEMS`), ad-hoc | 38W–0L, 5.82× geomean — the one peer that answers the whole shared surface                        |
| **vs trycast**, ad-hoc                 | 32W–2L, 3.23× geomean — **not unbeaten**: trycast is 1.28× faster on `list[int] x1000`            |
| **vs pydantic**, prepared              | 0.59× with `validator`, 0.92× with `compiled_validator` — a Rust core, drawn close but not passed |
| **vs msgspec**, ad-hoc                 | 0.32× geomean; up to 22.6× slower on `list[int] x1000`                                            |
| **Sampling libraries**                 | excluded from every race, and why is the point                                                    |

The most important finding is not a timing.
It is that **the fast numbers in this ecosystem are mostly fast because they answer a smaller question**, and that this is invisible unless you probe for it.
The second most important is the discipline that follows from it: the comparison is only worth publishing if it is arranged so that we can lose, and on this machine we lose to trycast twice, to pydantic on balance, and to msgspec badly.

---

## 2. Method

Two axes decide whether two numbers may be compared.
Both are established by measurement rather than reputation, and the classification is re-derived on every run by `contenders.audit()`.

### Tier — is it the same question?

| tier           | meaning                                                                             | libraries                                           |
|:---------------|:------------------------------------------------------------------------------------|:----------------------------------------------------|
| **exact**      | a verdict on the whole value, no allocation                                         | typing-validation, trycast, typeguard (`ALL_ITEMS`) |
| **rebuilding** | same verdict once coercion is off, but returns a **new object**                     | pydantic, msgspec, typedload, cattrs                |
| **sampling**   | checks O(1) items per container; returns `True` for values that are not of the type | beartype, typeguard (default)                       |

Two probes place every library: a 1000-element list whose **last** item is wrong separates checking from sampling (anything answering `True` did not look); a list of numeric strings against `list[int]` separates checking from coercing.

Rebuilding-tier figures carry an inherent handicap — the allocation cannot be switched off — so they are an upper bound on the cost of the question, never a like-for-like loss.
Sampling-tier figures are excluded from every race.

Every library in the rebuilding tier is measured with its alignment turned on, because the tier is *defined* as the same verdict once coercion is disabled: pydantic with `strict=True`, msgspec with `strict=True`, typedload with `basiccast=False`, and cattrs with structure hooks that refuse to coerce.
cattrs is the one that takes reading up on. It has no strictness *flag* — `detailed_validation` governs how much an error says, `forbid_extra_keys` governs extra keys, and neither is strictness — but coercion lives in per-class structure hooks, and overriding them is cattrs' own documented idiom: its `preconf` converters are built exactly that way, down to a shipped `validate_datetime` hook with the body this suite uses.
Configuring it costs cattrs about 15%, and is the only way its verdict is comparable with `validate`'s at all. A bare `Converter` would post a faster figure for a library that had been handed an easier question.

### Usage — is it asked the same way?

**Ad-hoc** takes the type per call and analyses it per call.
**Prepared** analyses once and returns a reusable callable.
Racing across this axis measures the API chosen, not the library.
This is not hypothetical: `typedload.load` builds a fresh `Loader` per call and is **a median of 4.6× slower** than a hoisted one — 13× on a bare `int`, where the construction is the whole cost — so timing only the module-level function would have reported our own API misuse as typedload's speed.

Accordingly `validate` races the ad-hoc APIs; `validator` and `compiled_validator` race the prepared ones.

### Corpus

- **Flat** (22 cases, `tools/cases.py`) — scalars, one-level collections, one recursive alias. JSON-shaped.
- **Extended** (33 cases, `tools/extended.py`) — eight features (scalar, collection, nested, structured, union, recursive, generic, numpy) measured alone, then crossed in the pairs and triples that are inhabitable and that people write. Not all 127 subsets: most are uninhabitable (a scalar cannot be recursive) or absurd (a `Literal` inside a dtype).

Every case was verified before timing: `valid` must validate, `invalid` must fail, and fail for the reason the case is named after.

### The shared surface, and this library's extensions

**The corpus is ours, and that is a bias worth naming rather than footnoting.**
17 of the 55 cases exercise a mechanism no peer implements: `__validate__`, the protocol by which a generic class says how its own arguments are checked, and the NumPy plugin.
A library that does not implement a protocol we invented is not *wrong* about those cases, it is not playing — and folding them into one percentage produces a figure whose real content is *typing-validation is the only library that is typing-validation*.

So the corpus carries the split in the code — `Case.extension` — and the report counts the two halves separately and never adds them up.
The reach is real, and is claimed as reach.
The agreement figure is the one a peer can argue with.

One asymmetry in that split is worth defending, because it looks like a double standard.
Section 7 argues that answering `True` for `Box("hi")` against `Box[int]` is *correct*, since a generic does not expose its arguments at runtime — and yet a library that answers `NDArray[uint8]` on its origin alone is counted as differing.
The difference is that a NumPy array *does* expose its dtype at runtime: `arr.dtype` is right there, so checking it is possible and declining to is a limitation rather than a principle.
That is why `Box` sits in the shared surface, where the peers agree with us, and NumPy sits in the extensions, where they cannot follow.

### Excluded from every figure

A wrong answer has no time.
Cases where a peer gave a differing verdict, or could not express the type, are excluded from that peer's record and itemised instead.
This is why the peer records are drawn from 11–38 cases each, and why the report prints the case count beside every geomean: two peers' geomeans are not comparable with each other, only with ours.

---

## 3. Agreement

How often each library returns this suite's verdict, on the 38 cases of the shared surface.
The full table, including the 17 extension cases counted separately, is in [`REPORT.md`](REPORT.md).

The column is *agrees*, not *correct*: on the shared surface the two coincide, and where they might not, the disagreement is itemised so a reader can judge for themselves.

| library                                      | agrees | differs | can't express | **% of 38** |
|:---------------------------------------------|:-------|:--------|:--------------|:------------|
| **typing-validation** (all three mechanisms) | **38** | 0       | 0             | **100%**    |
| **typeguard** (`ALL_ITEMS`)                  | **38** | 0       | 0             | **100%**    |
| pydantic (strict)                            | 36     | 0       | 2             | 95%         |
| trycast                                      | 34     | 3       | 1             | 89%         |
| msgspec (convert, strict)                    | 30     | 8       | 0             | 79%         |
| cattrs                                       | 30     | 8       | 0             | 79%         |
| typedload (`load`)                           | 29     | 9       | 0             | 76%         |
| typedload (`Loader`)                         | 29     | 1       | 8             | 76%         |
| typeguard (default)                          | 21     | 17      | 0             | 55%         |
| beartype (`is_bearable`)                     | 13     | 24      | 1             | 34%         |
| beartype (`TypeHint`)                        | 11     | 21      | 6             | 29%         |

**typeguard, told to check every item, is correct on every case we are correct on.**
That is the result, and it is why the extension cases are counted apart rather than folded in.
Folded in, they put typeguard at 69% and this library alone above that line — a line drawn by the corpus rather than measured.

pydantic's two gaps are `NDArray` and a runtime protocol; it is wrong about nothing, and its zero in the *differs* column is a real result that survives every way of counting.
The bottom of the table is not a ranking of quality.
typeguard's default and beartype's `is_bearable` sample by design, and cattrs' remaining eight are reach rather than coercion — a structured union wants a tag in the payload, and a recursive alias has no hook.
Each is answering a question it documents.

What the table *is* saying: **typing-validation's figures are drawn from the whole corpus, and everyone else's from a subset of it.**
That asymmetry is the finding, and no timing table shows it.

---

## 4. `validate` — ad-hoc

The full table, with the case count that makes each geomean readable, is `REPORT.md`'s *Records*.
The shape of it:

| peer                    | tier       | record | geomean | worst loss |
|:------------------------|:-----------|:-------|:--------|:-----------|
| typeguard (`ALL_ITEMS`) | exact      | 38W–0L | 5.82×   | —          |
| typedload (`load`)      | rebuilding | 27W–2L | 3.30×   | 2.5×       |
| trycast                 | exact      | 32W–2L | 3.23×   | 1.3×       |
| cattrs                  | rebuilding | 7W–23L | 0.60×   | 8.8×       |
| msgspec (strict)        | rebuilding | 5W–25L | 0.32×   | 22.6×      |

**Not unbeaten.**
trycast is **1.28× faster on `list[int] x1000`** — 89.6 µs against 115.1 µs — and that is not noise, it is the shape of the corpus: a thousand-element list is where per-element overhead is the entire cost, and our per-node dispatch costs more than trycast's.
The other loss, on `list[int] | list[str]`, is 0.98× and *is* noise.
One reproducible loss to an exact-tier peer is worth more to a reader than a round number, and it is the first thing anyone re-running this will find.

The serious losses are to libraries with compiled cores that rebuild the value.
msgspec is up to **22.6× faster on `list[int] x1000`** and agrees on the cases it wins.
Its shape is instructive — msgspec pays a fixed per-call cost whatever the type, so `validate` wins every scalar and loses every bulk container, with the crossover roughly where a container exceeds a handful of elements.

typeguard is the one peer that answers the whole shared surface, so 38W–0L at 5.82× is the most meaningful line in the table: it is the only row where the subset is not doing any of the work.

---

## 5. `validator` — prepared

| peer                 | record | geomean | worst loss              |
|:---------------------|:-------|:--------|:------------------------|
| typedload (`Loader`) | 29W–0L | 1.94×   | —                       |
| pydantic (strict)    | 9W–27L | 0.59×   | 7.7× (recursive `Tree`) |

`validator` analyses the type once into a graph and walks it per call.
Against pydantic's Rust core that is not enough: it wins scalars and NamedTuple, loses bulk and recursion.

---

## 6. `compiled_validator` — prepared

| peer                 | record  | geomean | worst loss              |
|:---------------------|:--------|:--------|:------------------------|
| typedload (`Loader`) | 29W–0L  | 2.97×   | —                       |
| pydantic (strict)    | 16W–20L | 0.92×   | 7.5× (recursive `Tree`) |

**This is where the design's central claim is tested, and the honest verdict is *close, and machine-dependent*.**
Compilation lifts the pydantic race from 0.59× to 0.92× and turns 9W–27L into 16W–20L, which is a large and reproducible improvement.
Whether that is enough to draw *level* is the one question this comparison cannot settle from a single machine.
The corpus has been run on two: an x86 Linux container, where it measured 1.11× and 20W–16L, and the ARM64 Windows machine that produced `REPORT.md`, where it measures 0.92× and 16W–20L.
Reporting either alone would be reporting the hardware.

The claim that survives both is worth more than the one that survives a single run: **pure-Python bytecode lands within roughly 10% of a Rust core on a like-for-like usage comparison, and which side is ahead depends on the machine.**
That is a real result, and it does not need the flattering rounding.

### Where compilation pays, and where it stops

Sorting all 55 cases by `validator → compiled` speedup splits the corpus in two, and the split is the point:

**Unrolls — 20 cases, 1.70–4.06×**

| speedup | case                                            |
|:--------|:------------------------------------------------|
| 4.06×   | `collection+structured: list[NamedTuple] x20`   |
| 3.35×   | `nested+structured: list[dict[str, Point]] x10` |
| 2.84×   | `nested: dict[str,list[dict[str,list[int]]]]`   |
| 2.69×   | `nested: list[dict[str, tuple[int,...]]] x20`   |
| 2.47×   | `shared subtype x20`                            |

**Flat — 35 cases, below 1.5× and mostly at 1.0×.**
Every one is a boundary `knowledge/TYPES.md` documents in advance:

| boundary                       | why the compiler stops                                      |
|:-------------------------------|:------------------------------------------------------------|
| generics behind `__validate__` | an opaque call — no source to inline                        |
| NumPy                          | plugin boundary — no source for the dtype check             |
| recursion through an alias     | the cycle must stop unrolling, by construction              |
| protocols                      | `isinstance` against a runtime protocol is already one call |
| scalars                        | one `isinstance`; nothing to unroll                         |

Where there is nothing to unroll the wrapper is not free: the slowest cases run at about **0.85×**, and they are a NumPy array, a `Checked[list[int]]` behind `__validate__`, a recursive alias, and a hundred-deep nested list — a plugin, an opaque call, a cycle, and CPython's refusal of more than a hundred levels of indentation. Four boundaries, all of them written down before they were measured.

**The compiler stops exactly where the design says it stops.**
That correspondence — between a spec written in advance and a measurement taken after — is the best evidence in this review that the architecture is what it claims to be, and it is the one claim here that reproduced on both machines the corpus has been run on: 20 cases unroll and 35 do not, on each.
The suite's own report says the table should say `never` rather than pretend; the extended corpus confirms it does.

### Build cost

Neither build is flat, and the difference between them is smaller than it looks from the per-call figures.
Over the flat corpus, `validator` costs **2.4 µs to 248.9 µs** from a cold cache — a 105× spread, tracking the size of the type rather than a constant — and `compiled_validator` costs **1.2× to 45× more** than it, median **6.8×**, reaching 2.0 ms on a hundred-deep nested list.
Both analyse the type; only the second then emits and compiles source, and that is the part that is not free.

`REPORT.md` quantifies the trade as a break-even, per case, which is the form that answers the question a caller has.
A median of 6.8× is worth reading twice before assuming the compiler's build is the expensive thing about it: on the cases where compilation buys nothing, the build it wasted was single-digit multiples of an analysis that had to happen anyway.

---

## 7. Generic classes: where typing-validation is alone

`knowledge/TYPES.md` is explicit that a generic class validates on **its origin alone**.
`validate(Box("hi"), Box[int])` is `True` — by design, because a generic does not in general expose its arguments at runtime.

On `Box("hi")` against `Box[int]`:

| library           | answer                                 |
|:------------------|:---------------------------------------|
| typing-validation | `True` — origin-only, per spec         |
| beartype          | `True` — agrees                        |
| typeguard         | `True` — agrees                        |
| trycast           | raises `TypeNotSupportedError`         |
| pydantic          | raises `PydanticSchemaGenerationError` |

The permissive answer is the *correct* one, and two of four peers cannot express the type at all.
What distinguishes typing-validation is the escape: declaring `__validate__` makes the argument checked — `Checked("a")` against `Checked[int]` is `False`.

It buys nothing from compilation, and is not claimed to.
A generic behind `__validate__` is an opaque call with no source to inline, so there is nothing there to unroll — exactly as section 6 says — and measured, those cases run at 0.85–0.96×: the wrapper's cost, and no more.
The capability is the point; the compiler is not part of it.

**No other library measured offers a route from origin-only to argument-checked.**
This is the clearest capability gap in the review, and it only appears because the corpus contains both `Box` (bare) and `Checked` (declaring).
A corpus with only one would have measured the wrong thing.

---

## 8. Findings about the peers

Three are worth reporting upstream.

**msgspec breaks on recursive aliases.**
It wins most of the flat corpus outright, then takes **3.5 ms** on a 121-node `Tree` — 20.8× slower than `validate` here — *and* **rejects the valid tree outright**.
Milliseconds on a tree that small is not a slow path, it is a different algorithm, and the wrong verdict is the more serious half of it.
The flat corpus would never have found this.
The ratio is quoted with the machine it came from because it moves a great deal with the hardware; the effect does not.

**typedload's `Loader` raises `AssertionError` on NamedTuple.**
An internal `assert isinstance(e, TypedloadException)` fires *while handling* an exception, so the library raises from its own error path.
`typedload.load` on the same case raises cleanly.
Likely a genuine bug.

**beartype has two entry points with two supported surfaces.**
`TypeHint(t).is_bearable(v)` rejects six type forms that `is_bearable(v, t)` accepts — nested lists, shared subtypes, recursive aliases, and all three NumPy forms.

And one that is not a bug: **beartype's `BeartypeStrategy.On`** (linear checking) is documented in beartype's own source as unimplemented.
Passing it silently returns the O(1) answer rather than failing.
Anyone benchmarking beartype as an exact checker by setting that flag will measure a sampling library and believe otherwise.

---

## 9. Why sampling libraries are excluded

The clearest statement of the whole review, from two rows:

| library                      | `list[int]` x20 | `list[int]` x1000 | ratio    |
|:-----------------------------|:----------------|:------------------|:---------|
| typing-validation (compiled) | 561 ns          | 22.6 µs           | **40×**  |
| beartype (`is_bearable`)     | 419 ns          | 443 ns            | **1.1×** |

Fifty times the data, fifty times the work — that is the price of the answer being right.
beartype's flat line is not a faster check; it is a check that did not look at the thousandth item, and the report marks both of those cells ⚠ because it accepted the invalid value in each.
On the shared surface `is_bearable` differs from this suite on 24 of 38 cases.

Note the other half of the row: **beartype is faster than us on the small list too**, and on a corpus of small containers it would look faster still.
That is not the trade being criticised. The criticism is only that the two figures answer different questions, and that nothing in a timing table says so.

This is a deliberate, well-argued trade on beartype's part, and for its intended use — a decorator on every function in a hot codebase — it is very likely the right one.
It is simply not the same question, and timing it against a full check measures the corpus rather than the library.

---

## 10. Recommendations

**Publish the tiering.**
It is the most valuable output here and it is not specific to this library: the ecosystem has no shared vocabulary for the difference between checking, sampling, and rebuilding, and the absence lets benchmarks compare things that cannot be compared.

**Claim reach first, speed second — and do not claim correctness.**
A correctness percentage over this corpus is not a claim about the field, it is a claim about the corpus: fold the extension cases in and typeguard reads 69%, leaving this library apparently alone above the line. On the shared surface typeguard is correct on everything we are correct on, and no honest arrangement of these numbers says otherwise.

What is left is stronger, and is the claim that survives an unfriendly re-run: **typing-validation reaches type forms nothing else measured reaches** — a generic's arguments, a NumPy dtype — and it is exact and fast on the rest.
Surviving someone else's re-run is the only test that matters for a document like this.

**Do not chase msgspec on bulk containers.**
The 22.6× gap on `list[int] x1000` is a Rust core against interpreted bytecode.
It is not closable by tuning, and `compiled_validator` already extracts most of what the strategy allows.

**Do look at `validate` on bulk containers, where the loss is to a peer and not to a compiler.**
trycast is 1.28× faster on `list[int] x1000` doing the same work in the same language.
That is the one shape where something in the design is costing more than it needs to, and it is the only speed finding here that is neither a Rust core nor a difference of question.

**Do not read the build costs as a reason to prefer the middle mechanism.**
Neither build is flat, `validator`'s spans 105× across the corpus, and `compiled_validator`'s is a median of 6.8× more rather than the order of magnitude the per-call figures suggest.
Where the headroom is, per case, is a question `REPORT.md`'s break-even table answers directly and this document should not guess at.

**Two open questions this review raises but does not answer.**
Whether `compiled_validator` should fall back to `validator` automatically when the inlining budget finds nothing to unroll — 35 of the 55 cases buy nothing from compiling, and pay a median of 6.8× the analysis they needed anyway to find that out — and whether the `__validate__` protocol should be documented as the ecosystem's answer to generic arguments rather than as a local feature.

---

## 11. Reproducing

```bash
uv sync --group dev --group peers
python -m benchmark --write        # REPORT.md, both corpora, both halves
```

Cases: `benchmark/tools/cases.py` (flat), `benchmark/tools/extended.py` (extended).
Contenders and the tier audit: `benchmark/tools/contenders.py`.
Measurement, with support and verdict settled before the clock starts: `benchmark/tools/compare.py`.

Measured on Python 3.14.4 against typing-validation 2.2.0, with beartype 0.22.9, cattrs 26.1.0, msgspec 0.21.1, numpy 2.5.1, pydantic 2.13.4, trycast 1.3.0, typedload 2.41, typeguard 4.5.2.
Full environment in `REPORT.md`.
