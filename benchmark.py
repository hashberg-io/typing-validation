"""
Rough and messy basic benchmarking code. Will be replaced by a suitable random generation module
in the future (likely absorbing the one currently implemented by [dag-cbor](https://github.com/hashberg-io/dag-cbor)).

Validation takes around 5ns per byte of validation data on my machine.
Note that union type validation multiplies the number of data bytes by the number of types in the union,
for uniformity of comparison with other validation cases.

1.557ns/B sumprod (100000 iters)
1.225ns/B append (100000 iters)
4.817ns/B validate <class 'int'> (100000 iters)
3.207ns/B validate <class 'bytes'> (10000 iters)
0.431ns/B validate <class 'list'> (10000 iters)
0.195ns/B validate <class 'dict'> (10000 iters)
6.956ns/B validate typing.List[int] (10000 iters)
5.139ns/B validate typing.List[typing.List[int]] (10000 iters)
3.742ns/B validate typing.Dict[int, int] (10000 iters)
5.090ns/B validate typing.Union[int, list[int], typing.Dict[int, int]] (10000 iters)
"""

import random
import sys
from time import time, perf_counter

from typing import Any, Dict, List, Tuple, Union
from typing_validation import validate

_MIN_INT = -1_000_000
_MAX_INT = 1_000_000

def _rand_ints(nvals: int, *, min_int: int = _MIN_INT, max_int: int = _MAX_INT) -> Tuple[List[int], int]:
    vals = [random.randrange(min_int, max_int) for _ in range(nvals)]
    size = sum(sys.getsizeof(val) for val in vals)
    return vals, size

def _rand_bytestrs(nvals: int, *, max_length: int = 20) -> Tuple[List[bytes], int]:
    lengths: List[int] = _rand_ints(nvals, min_int=0, max_int=max_length)[0]
    vals = []
    size = 0
    for length in lengths:
        val = random.randbytes(length)
        vals.append(val)
        size += sys.getsizeof(val)
    return vals, size

def _rand_lists(t: Any, nvals: int, *, max_length: int = 20) -> Tuple[List[Any], int]:
    lengths: List[int] = _rand_ints(nvals, min_int=0, max_int=max_length)[0]
    vals = []
    size = 0
    for length in lengths:
        val, items_size = rand_vals(t, length)
        vals.append(val)
        size += items_size+sys.getsizeof(val)
    return vals, size

def _rand_dicts(k: Any, v: Any, nvals: int, *, max_length: int = 20) -> Tuple[List[Any], int]:
    lengths: List[int] = _rand_ints(nvals, min_int=0, max_int=max_length)[0]
    vals = []
    size = 0
    for length in lengths:
        key_list, keys_size = rand_vals(k, length)
        value_list, values_size = rand_vals(v, length)
        val = dict(zip(key_list, value_list))
        vals.append(val)
        size += keys_size+values_size+sys.getsizeof(val)
    return vals, size

def _rand_union(ts: Tuple[Any], nvals: int) -> Tuple[List[Any], int]:
    indices = _rand_ints(nvals, min_int=0, max_int=len(ts))[0]
    vals = []
    size = 0
    for idx in indices:
        val_lst, val_size = rand_vals(ts[idx], 1)
        vals.append(val_lst[0])
        size += val_size
    return vals, size*len(ts)

def rand_vals(t: Any, nvals: int, seed: int = 0) -> Tuple[List[Any], int]:
    random.seed(seed)
    if t == list:
        t = List[int]
    if t == dict:
        t = Dict[int, int]
    if t == int:
        return _rand_ints(nvals)
    if t == bytes:
        return _rand_bytestrs(nvals)
    if t.__origin__ == list:
        return _rand_lists(t.__args__[0], nvals)
    if t.__origin__ == dict:
        return _rand_dicts(t.__args__[0], t.__args__[1], nvals)
    if t.__origin__ is Union:
        return _rand_union(t.__args__, nvals)
    raise ValueError(f"Unsupported type {repr(t)}")

def benchmark(t: Any, niters: int, seed: int = 0) -> None:
    vals, size = rand_vals(t, niters, seed=seed)
    start = perf_counter()
    for val in vals:
        validate(val, t)
    end = perf_counter()
    ns = (end-start)*1e9/size
    print(f"{ns:.3f}ns/B validate {repr(t)} ({niters} iters)")

def benchmark_sumprod(niters: int, seed: int = 0) -> None:
    random.seed(seed)
    xs, xsize = _rand_ints(niters)
    ys, ysize = _rand_ints(niters)
    size = xsize+ysize
    start = perf_counter()
    sp = 0
    for x, y in zip(xs, ys):
        sp += x*y
    end = perf_counter()
    ns = (end-start)*1e9/size
    print(f"{ns:.3f}ns/B sumprod ({niters} iters)")

def benchmark_append(niters: int, seed: int = 0) -> None:
    random.seed(seed)
    xs, size = _rand_ints(niters)
    start = perf_counter()
    l = []
    for x in xs:
        l.append(x)
    end = perf_counter()
    ns = (end-start)*1e9/size
    print(f"{ns:.3f}ns/B append ({niters} iters)")

if __name__ == "__main__":
    benchmark_sumprod(100_000, seed=int(time()))
    benchmark_append(100_000, seed=int(time()))
    benchmark(int, 100_000, seed=int(time()))
    benchmark(bytes, 10_000, seed=int(time()))
    benchmark(list, 10_000, seed=int(time()))
    benchmark(dict, 10_000, seed=int(time()))
    benchmark(List[int], 10_000, seed=int(time()))
    benchmark(List[List[int]], 10_000, seed=int(time()))
    benchmark(Dict[int, int], 10_000, seed=int(time()))
    benchmark(Union[int, list[int], Dict[int, int]], 10_000, seed=int(time()))
