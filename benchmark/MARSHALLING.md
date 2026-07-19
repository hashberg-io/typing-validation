# Marshalling: would it earn its risk?

## The whole prize, in one place

Building every one of the 16 compilable types in the corpus, in one process:

| | cost |
|:--|---:|
| `compiled_validator` for all of them, cold | 8.00 ms |
| the same, loaded from a marshalled cache | 448.5 µs |
| **saved** | **7.55 ms** |
| `validator` for all of them, no cache needed | 758.3 µs |
| importing `typing_validation` at all | 24.83 ms |

The last two rows are the ones that decide it, and neither is about the compiled path.

**Against `validator`.** A cache saves 7.55 ms over compiling, but a caller who simply composed instead would have paid 758.3 µs — within 309.8 µs of the cache, with no cache. So the cache is not buying startup time, which was already available. It is buying the compiled path's *run* speed at the composed path's startup, and that is the only claim it can make.

**Against the import.** The whole saving is 7.55 ms, and importing the library at all costs 24.83 ms — a ratio of 0.3x. Read it as a scale, not a verdict: this is the entire corpus built in one process, so a caller with a handful of types has a proportionally smaller prize.

Exploratory measurement, not part of the report. See the module docstring of `benchmark/marshalling.py` for what each phase is and why two of the four are unavoidable.

## Where construction time goes

`node` and `exec` are paid by a marshalled load too. Only `emit` and `compile` could ever be skipped.

`sum/build` is the consistency check: the phases are timed separately and the build whole, so a row far from 100% moved between the two and should not be read.

| Case | node | decide | emit | compile | exec | sum | cold build | sum/build | skippable |
|:-----|-----:|-------:|-----:|--------:|-----:|----:|-----------:|----------:|----------:|
| int | 1.5 µs | 2.2 µs | 1.8 µs | 16.5 µs | 211 ns | 22.2 µs | 24.7 µs | 90% | 83% |
| str | 2.6 µs | 3.9 µs | 3.3 µs | 20.8 µs | 274 ns | 30.9 µs | 24.8 µs | 125% | 113% |
| list[int] x20 | 2.8 µs | 4.7 µs | 4.6 µs | 26.7 µs | 215 ns | 39.0 µs | 43.3 µs | 90% | 83% |
| list[int] x1000 | 5.1 µs | 10.2 µs | 8.1 µs | 34.2 µs | 205 ns | 57.8 µs | 45.3 µs | 128% | 116% |
| list[str] x20 | 4.4 µs | 7.5 µs | 5.3 µs | 26.7 µs | 225 ns | 44.1 µs | 43.6 µs | 101% | 90% |
| set[int] x20 | 2.8 µs | 4.8 µs | 4.6 µs | 27.0 µs | 220 ns | 39.4 µs | 45.1 µs | 87% | 81% |
| nested list x100 | 143.9 µs | 904.6 µs | 962.2 µs | 408.6 µs | 510 ns | 2.42 ms | 4.61 ms | 52% | 49% |
| dict[str, int] x20 | 4.1 µs | 6.8 µs | 6.8 µs | 37.4 µs | 229 ns | 55.3 µs | 62.8 µs | 88% | 81% |
| tuple[int, str] | 4.8 µs | 6.5 µs | 6.6 µs | 40.7 µs | 210 ns | 58.8 µs | 65.6 µs | 90% | 82% |
| tuple[int, ...] x20 | 2.9 µs | 4.8 µs | 4.5 µs | 27.0 µs | 223 ns | 39.4 µs | 45.7 µs | 86% | 79% |
| int | None (plain) | 5.0 µs | 4.6 µs | 3.8 µs | 16.8 µs | 218 ns | 30.3 µs | 33.4 µs | 91% | 75% |
| int | str | None (plain) | 4.8 µs | 4.0 µs | 3.7 µs | 16.4 µs | 213 ns | 29.1 µs | 36.8 µs | 79% | 65% |
| TypedDict | 6.1 µs | 7.7 µs | 8.1 µs | 57.0 µs | 254 ns | 79.0 µs | 90.3 µs | 88% | 81% |
| NamedTuple | 4.8 µs | 6.0 µs | 5.8 µs | 31.9 µs | 242 ns | 48.8 µs | 54.6 µs | 89% | 80% |
| shared subtype x20 | 15.5 µs | 317.0 µs | 326.3 µs | 840.6 µs | 417 ns | 1.50 ms | 1.60 ms | 94% | 93% |
| TypedDict x40 fields | 49.2 µs | 99.6 µs | 117.8 µs | 862.7 µs | 384 ns | 1.13 ms | 1.17 ms | 97% | 92% |

## What a load would cost, and what it would save

The load path is `node` + `unmarshal` + `recipe` + `exec`. The recipe is the globals rebuild: a class can never be a code constant, so every one the check names has to be resolved back by `module:qualname`.

| Case | unmarshal | recipe | load total | cold build | net | blob |
|:-----|----------:|-------:|-----------:|-----------:|----:|-----:|
| int | 798 ns | 574 ns | 3.1 µs | 24.7 µs | +87% | 277 B |
| str | 818 ns | 571 ns | 4.3 µs | 24.8 µs | +83% | 277 B |
| list[int] x20 | 908 ns | 1.1 µs | 5.0 µs | 43.3 µs | +88% | 386 B |
| list[int] x1000 | 859 ns | 1.1 µs | 7.2 µs | 45.3 µs | +84% | 386 B |
| list[str] x20 | 883 ns | 1.1 µs | 6.6 µs | 43.6 µs | +85% | 386 B |
| set[int] x20 | 904 ns | 1.1 µs | 5.0 µs | 45.1 µs | +89% | 386 B |
| nested list x100 | 5.8 µs | 11.9 µs | 162.1 µs | 4.61 ms | +96% | 2315 B |
| dict[str, int] x20 | 1.1 µs | 1.6 µs | 7.0 µs | 62.8 µs | +89% | 512 B |
| tuple[int, str] | 1.1 µs | 1.1 µs | 7.2 µs | 65.6 µs | +89% | 510 B |
| tuple[int, ...] x20 | 890 ns | 569 ns | 4.6 µs | 45.7 µs | +90% | 386 B |
| int | None (plain) | 784 ns | 1.9 µs | 7.8 µs | 33.4 µs | +77% | 281 B |
| int | str | None (plain) | 775 ns | 2.4 µs | 8.2 µs | 36.8 µs | +78% | 281 B |
| TypedDict | 1.4 µs | 1.7 µs | 9.4 µs | 90.3 µs | +90% | 687 B |
| NamedTuple | 1.1 µs | 1.6 µs | 7.7 µs | 54.6 µs | +86% | 473 B |
| shared subtype x20 | 17.1 µs | 66.1 µs | 99.1 µs | 1.60 ms | +94% | 8949 B |
| TypedDict x40 fields | 14.8 µs | 40.0 µs | 104.3 µs | 1.17 ms | +91% | 8011 B |

## The comparison that decides it

Marshalling's only coherent claim is *the compiled path's run speed at the composed path's build cost*. So the number a load has to beat is `validator(t)`, which a caller can already have without any cache at all. `load/composed` below 100% means the claim holds.

| Case | marshalled load | `validator(t)` build | load/composed |
|:-----|----------------:|---------------------:|--------------:|
| int | 3.1 µs | 2.9 µs | 107% |
| str | 4.3 µs | 2.9 µs | 148% |
| list[int] x20 | 5.0 µs | 5.9 µs | 85% |
| list[int] x1000 | 7.2 µs | 6.0 µs | 120% |
| list[str] x20 | 6.6 µs | 6.0 µs | 111% |
| set[int] x20 | 5.0 µs | 6.1 µs | 83% |
| nested list x100 | 162.1 µs | 508.3 µs | 32% |
| dict[str, int] x20 | 7.0 µs | 8.8 µs | 80% |
| tuple[int, str] | 7.2 µs | 9.1 µs | 79% |
| tuple[int, ...] x20 | 4.6 µs | 6.2 µs | 74% |
| int | None (plain) | 7.8 µs | 7.1 µs | 110% |
| int | str | None (plain) | 8.2 µs | 9.4 µs | 88% |
| TypedDict | 9.4 µs | 10.8 µs | 87% |
| NamedTuple | 7.7 µs | 8.5 µs | 90% |
| shared subtype x20 | 99.1 µs | 41.1 µs | 241% |
| TypedDict x40 fields | 104.3 µs | 119.3 µs | 87% |

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
