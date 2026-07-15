# typing-validation

[![Python versions](https://img.shields.io/badge/python-3.14+-green.svg)](https://docs.python.org/3.14/)
[![PyPI version](https://img.shields.io/pypi/v/typing-validation.svg)](https://pypi.python.org/pypi/typing-validation/)
[![PyPI status](https://img.shields.io/pypi/status/typing-validation.svg)](https://pypi.python.org/pypi/typing-validation/)
[![Checked with Mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](https://github.com/python/mypy)
[![Documentation Status](https://readthedocs.org/projects/typing-validation/badge/?version=latest)](https://typing-validation.readthedocs.io/en/latest/?badge=latest)

A library to perform runtime validation of Python objects using type hints.

## Install

Install the latest release from [PyPI](https://pypi.org/project/typing-validation/):

```console
$ pip install --upgrade typing-validation
```

## Usage

Validate a value against a type hint. `validate` returns `True` on success and raises on failure:

```python
>>> from typing_validation import validate
>>> validate([1, 2, 3], list[int])
True
```

The `True` return exists so that validation can be gated behind an assertion, and compiled out entirely under `-O`:

```python
assert validate(val, t)
```

When a value does not conform, the error says **where**:

```python
>>> validate({"a": [1, "b"]}, dict[str, list[int]])
Traceback (most recent call last):
  ...
typing_validation.errors.ValidationError: For type dict[str, list[int]]: a component failed
  For type list[int] value at key 'a': a component failed
    For type <class 'int'> index 1: not an instance, got 'b'
```

The structured explanation is on the exception, for reading programmatically:

```python
>>> try:
...     validate([1, "b"], list[int])
... except ValidationError as e:
...     print(e.failure.causes[0].location.at)
1
```

### Validating the same type repeatedly

`validate` analyses the type on every call. When you validate many values against
one type, `validator` analyses it once and hands back a function:

```python
>>> from typing_validation import validator
>>> check = validator(list[int])
>>> check([1, 2, 3])
True
```

Same contract, same verdict, **2.7× faster per call**. It repays the cost of
building it almost immediately — the benchmark suite reports exactly when, per
type:

| Type | `validate` | `validator` | repays after |
|---|---|---|---|
| `list[int]` (1000 items) | 61.3 µs | 22.6 µs | 0 values |
| `list[int]` (20 items) | 1.50 µs | 0.54 µs | 3 values |
| `dict[str, int]` (20 items) | 2.79 µs | 1.04 µs | 3 values |
| `tuple[int, str]` | 436 ns | 216 ns | 22 values |
| `int` | 51.9 ns | 46.8 ns | 303 values |

So: use `validate` for one-off checks, and `validator` when the type is fixed and
the values keep coming. Run `python -m benchmark` for the numbers on your machine.

One difference, and it is deliberate. `validator` analyses the whole type before
it sees any value, so it **rejects an unsupported type immediately**:

```python
validator(list[Callable[[int], int]])   # UnsupportedTypeError, at once
validate([], list[Callable[[int], int]])  # True — no value reached the Callable
```

### The rest of the surface

```python
from typing_validation import is_valid, validated, validated_iter

is_valid([1, "a"], list[int])       # False — a boolean, at boolean prices
validated(payload, list[int])       # returns payload, for use in an expression
validated_iter(stream, Iterator[int])  # checks each item as it is yielded
```

`is_valid` deliberately builds no explanation: a caller who wants one calls `validate` and catches the exception.

`validated_iter` is not a convenience wrapper. Determining the items of a one-shot iterator consumes it, so `Iterator[int]` cannot check its items eagerly without destroying the value — checking them on the way past is the only honest way.

### Asking about a type

Support is all-or-nothing: if any component of a type is unsupported, the whole type is. `can_validate` answers up front:

```python
>>> from typing_validation import can_validate, inspect_type
>>> can_validate(list[int])
True
>>> can_validate(tuple[int, Callable[[int], int]])   # poisoned by the Callable
False
```

`inspect_type` returns the whole structure and names precisely what poisoned it, so "unsupported" is never opaque:

```python
>>> node = inspect_type(tuple[int, Callable[[int], int]])
>>> [c.t for c in node.unsupported_components()]
[typing.Callable[[int], int]]
```

### NumPy

NumPy array types are supported by an extension, which you enable by importing:

```python
import typing_validation.numpy   # required
from numpy.typing import NDArray

validate(np.array([1, 2], dtype=np.uint8), NDArray[np.uint8])
```

The import is required rather than automatic, so that the supported surface never depends on whether some unrelated dependency happened to import NumPy.

### Extending

A parametrised class can say how its own type arguments are validated:

```python
class Box[T]:
    @classmethod
    def __validate__(cls, val, args):
        return is_valid(val.item, args[0])
```

For classes you do not own, use `register_validator(cls, check)`.

## API

The full API documentation is available at
[typing-validation.readthedocs.io](https://typing-validation.readthedocs.io/).

## Structure

- `typing_validation/` — the package source.
- `knowledge/` — design documents: the architecture, and the catalogue of supported type forms.
- `test/` — the conformance suite, with the case corpus in `test/cases.py`.
- `benchmark/` — the benchmark suite; run it with `python -m benchmark`.
- `docs/` — the Sphinx documentation pipeline.

## License

[LGPL-3.0-or-later](LICENSE) © Hashberg Ltd
