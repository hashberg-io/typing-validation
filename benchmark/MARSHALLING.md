# Marshalling: would it earn its risk?

## The whole prize, in one place

Building every one of the 16 compilable types in the corpus, in one process:

| | cost |
|:--|---:|
| `compiled_validator` for all of them, cold | 7.05 ms |
| the same, loaded from a marshalled cache | 399.5 µs |
| **saved** | **6.65 ms** |
| `validator` for all of them, no cache needed | 642.6 µs |
| importing `typing_validation` at all | -66653600 ns |

The last two rows are the ones that decide it, and neither is about the compiled path.

**Against `validator`.** A cache saves 6.65 ms over compiling, but a caller who simply composed instead would have paid 642.6 µs — within 243.1 µs of the cache, with no cache. So the cache is not buying startup time, which was already available. It is buying the compiled path's *run* speed at the composed path's startup, and that is the only claim it can make.

**Against the import.** The whole saving is 6.65 ms, and importing the library at all costs -66653600 ns — a ratio of -0.1x. Read it as a scale, not a verdict: this is the entire corpus built in one process, so a caller with a handful of types has a proportionally smaller prize.

Exploratory measurement, not part of the report. See the module docstring of `benchmark/marshalling.py` for what each phase is and why two of the four are unavoidable.

## Where construction time goes

`node` and `exec` are paid by a marshalled load too. Only `emit` and `compile` could ever be skipped.

`sum/build` is the consistency check: the phases are timed separately and the build whole, so a row far from 100% moved between the two and should not be read.

| Case | node | decide | emit | compile | exec | sum | cold build | sum/build | skippable |
|:-----|-----:|-------:|-----:|--------:|-----:|----:|-----------:|----------:|----------:|
| int | 1.5 µs | 2.2 µs | 1.8 µs | 16.8 µs | 221 ns | 22.5 µs | 26.6 µs | 85% | 78% |
| str | 1.5 µs | 2.2 µs | 1.8 µs | 16.3 µs | 211 ns | 22.0 µs | 25.0 µs | 88% | 81% |
| list[int] x20 | 2.9 µs | 4.8 µs | 4.6 µs | 27.5 µs | 222 ns | 40.0 µs | 44.4 µs | 90% | 83% |
| list[int] x1000 | 2.8 µs | 4.8 µs | 4.7 µs | 26.9 µs | 250 ns | 39.4 µs | 43.8 µs | 90% | 83% |
| list[str] x20 | 2.8 µs | 4.8 µs | 4.6 µs | 27.3 µs | 224 ns | 39.7 µs | 45.0 µs | 88% | 81% |
| set[int] x20 | 2.9 µs | 4.8 µs | 4.7 µs | 26.9 µs | 224 ns | 39.5 µs | 46.6 µs | 85% | 78% |
| nested list x100 | 142.7 µs | 919.8 µs | 930.6 µs | 304.6 µs | 1.1 µs | 2.30 ms | 3.64 ms | 63% | 59% |
| dict[str, int] x20 | 4.1 µs | 7.0 µs | 6.9 µs | 36.0 µs | 216 ns | 54.2 µs | 61.0 µs | 89% | 82% |
| tuple[int, str] | 5.7 µs | 9.0 µs | 7.6 µs | 42.0 µs | 231 ns | 64.5 µs | 64.4 µs | 100% | 91% |
| tuple[int, ...] x20 | 3.4 µs | 5.5 µs | 4.6 µs | 27.5 µs | 238 ns | 41.3 µs | 44.6 µs | 93% | 84% |
| int | None (plain) | 3.7 µs | 3.3 µs | 3.0 µs | 16.6 µs | 237 ns | 26.8 µs | 33.7 µs | 80% | 68% |
| int | str | None (plain) | 4.9 µs | 3.9 µs | 3.6 µs | 16.5 µs | 215 ns | 29.2 µs | 35.2 µs | 83% | 68% |
| TypedDict | 6.1 µs | 7.7 µs | 8.1 µs | 57.4 µs | 243 ns | 79.5 µs | 90.0 µs | 88% | 81% |
| NamedTuple | 4.8 µs | 6.1 µs | 5.9 µs | 30.2 µs | 231 ns | 47.3 µs | 52.5 µs | 90% | 80% |
| shared subtype x20 | 13.8 µs | 290.8 µs | 308.7 µs | 837.1 µs | 347 ns | 1.45 ms | 1.62 ms | 90% | 89% |
| TypedDict x40 fields | 44.2 µs | 95.8 µs | 110.6 µs | 856.0 µs | 407 ns | 1.11 ms | 1.18 ms | 94% | 90% |

## What a load would cost, and what it would save

The load path is `node` + `unmarshal` + `recipe` + `exec`. The recipe is the globals rebuild: a class can never be a code constant, so every one the check names has to be resolved back by `module:qualname`.

| Case | unmarshal | recipe | load total | cold build | net | blob |
|:-----|----------:|-------:|-----------:|-----------:|----:|-----:|
| int | 827 ns | 573 ns | 3.1 µs | 26.6 µs | +88% | 277 B |
| str | 788 ns | 571 ns | 3.0 µs | 25.0 µs | +88% | 277 B |
| list[int] x20 | 978 ns | 1.1 µs | 5.1 µs | 44.4 µs | +88% | 386 B |
| list[int] x1000 | 972 ns | 1.1 µs | 5.1 µs | 43.8 µs | +88% | 386 B |
| list[str] x20 | 994 ns | 1.1 µs | 5.1 µs | 45.0 µs | +89% | 386 B |
| set[int] x20 | 931 ns | 1.1 µs | 5.1 µs | 46.6 µs | +89% | 386 B |
| nested list x100 | 3.5 µs | 11.8 µs | 159.1 µs | 3.64 ms | +96% | 2315 B |
| dict[str, int] x20 | 1.1 µs | 1.6 µs | 7.0 µs | 61.0 µs | +89% | 512 B |
| tuple[int, str] | 1.0 µs | 1.1 µs | 8.0 µs | 64.4 µs | +88% | 510 B |
| tuple[int, ...] x20 | 923 ns | 573 ns | 5.1 µs | 44.6 µs | +89% | 386 B |
| int | None (plain) | 801 ns | 1.9 µs | 6.7 µs | 33.7 µs | +80% | 281 B |
| int | str | None (plain) | 819 ns | 2.3 µs | 8.3 µs | 35.2 µs | +76% | 281 B |
| TypedDict | 1.3 µs | 1.7 µs | 9.4 µs | 90.0 µs | +90% | 687 B |
| NamedTuple | 988 ns | 1.7 µs | 7.7 µs | 52.5 µs | +85% | 473 B |
| shared subtype x20 | 11.5 µs | 52.5 µs | 78.1 µs | 1.62 ms | +95% | 8949 B |
| TypedDict x40 fields | 10.5 µs | 28.3 µs | 83.4 µs | 1.18 ms | +93% | 8011 B |

## The comparison that decides it

Marshalling's only coherent claim is *the compiled path's run speed at the composed path's build cost*. So the number a load has to beat is `validator(t)`, which a caller can already have without any cache at all. `load/composed` below 100% means the claim holds.

| Case | marshalled load | `validator(t)` build | load/composed |
|:-----|----------------:|---------------------:|--------------:|
| int | 3.1 µs | 2.9 µs | 106% |
| str | 3.0 µs | 2.9 µs | 104% |
| list[int] x20 | 5.1 µs | 5.9 µs | 87% |
| list[int] x1000 | 5.1 µs | 6.0 µs | 85% |
| list[str] x20 | 5.1 µs | 5.9 µs | 87% |
| set[int] x20 | 5.1 µs | 6.0 µs | 86% |
| nested list x100 | 159.1 µs | 423.2 µs | 38% |
| dict[str, int] x20 | 7.0 µs | 8.7 µs | 80% |
| tuple[int, str] | 8.0 µs | 8.9 µs | 90% |
| tuple[int, ...] x20 | 5.1 µs | 6.1 µs | 83% |
| int | None (plain) | 6.7 µs | 7.2 µs | 93% |
| int | str | None (plain) | 8.3 µs | 9.3 µs | 89% |
| TypedDict | 9.4 µs | 10.7 µs | 87% |
| NamedTuple | 7.7 µs | 8.6 µs | 90% |
| shared subtype x20 | 78.1 µs | 44.5 µs | 176% |
| TypedDict x40 fields | 83.4 µs | 85.7 µs | 97% |

## What is in the globals

A runner is a composed closure, which cannot be marshalled and has to be rebuilt from the node graph — the second, independent reason a load cannot skip `node`.

`unresolvable` counts classes whose `module:qualname` does not lead back to them. Each is a type a real implementation would have to refuse to cache.

| Case | classes | runners | other | unresolvable |
|:-----|--------:|--------:|------:|-------------:|
| int | 1 | 0 | 0 | 0 |
| str | 1 | 0 | 0 | 0 |
| list[int] x20 | 2 | 0 | 0 | 0 |
| list[int] x1000 | 2 | 0 | 0 | 0 |
| list[str] x20 | 2 | 0 | 0 | 0 |
| set[int] x20 | 2 | 0 | 0 | 0 |
| nested list x100 | 16 | 1 | 0 | 0 |
| dict[str, int] x20 | 3 | 0 | 0 | 0 |
| tuple[int, str] | 2 | 0 | 0 | 0 |
| tuple[int, ...] x20 | 1 | 0 | 0 | 0 |
| int | None (plain) | 1 | 0 | 0 | 0 |
| int | str | None (plain) | 1 | 0 | 0 | 0 |
| TypedDict | 3 | 0 | 1 | 0 |
| NamedTuple | 3 | 0 | 0 | 0 |
| shared subtype x20 | 80 | 0 | 0 | 0 |
| TypedDict x40 fields | 41 | 0 | 1 | 0 |

## Cases with nothing to marshal

`compiled_validator` returns `validator(t)` for these, so there is no code object. Marshalling does not apply, rather than failing.

- list[int] | list[str] (structured)
- Literal[1, 2, 3]
- recursive alias (JSON)
- NDArray[uint8] x20
- NDArray[uint8] x10000
- ndarray[(int, int), uint8]
