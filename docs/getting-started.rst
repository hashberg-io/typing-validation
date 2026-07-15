Getting Started
===============

A library to perform runtime validation of Python objects using type hints.

You can install the latest release from `PyPI <https://pypi.org/project/typing-validation/>`_ as follows:

.. code-block:: console

    $ pip install --upgrade typing-validation

Validating a value
------------------

:func:`~typing_validation.validation.validate` checks a value against a type hint, returning :obj:`True` or raising:

.. code-block:: python

    >>> from typing_validation import validate
    >>> validate([1, 2, 3], list[int])
    True

The :obj:`True` return exists so that validation can be gated behind an assertion, and compiled out entirely under
``-O``:

.. code-block:: python

    assert validate(val, t)

When a value does not conform, the error says **where**:

.. code-block:: python

    >>> validate({"a": [1, "b"]}, dict[str, list[int]])
    Traceback (most recent call last):
      ...
    typing_validation.errors.ValidationError: For type dict[str, list[int]]: a component failed
      For type list[int] value at key 'a': a component failed
        For type <class 'int'> index 1: not an instance, got 'b'

The same explanation is available as a structure, on the exception, via
:attr:`~typing_validation.errors.ValidationError.failure`.

Validating the same type repeatedly
-----------------------------------

:func:`~typing_validation.validation.validate` analyses the type on every call.
When many values are validated against one type,
:func:`~typing_validation.composition.validator` analyses it once and returns a
function:

.. code-block:: python

    >>> from typing_validation import validator
    >>> check = validator(list[int])
    >>> check([1, 2, 3])
    True

Same contract, same verdict, and about 2.7x faster per call. It repays the cost
of building it almost at once — the benchmark suite reports exactly when, per
type: nought to four values for a container, twenty-two for a fixed tuple, a few
hundred for a scalar. So :func:`~typing_validation.validation.validate` for a
one-off check, and :func:`~typing_validation.composition.validator` when the type
is fixed and the values keep coming.

And when the values keep coming in very large numbers,
:func:`~typing_validation.emission.compiled_validator` emits Python specialised
to the type and compiles it:

.. code-block:: python

    >>> from typing_validation import compiled_validator
    >>> check = compiled_validator(list[int])
    >>> check([1, 2, 3])
    True

That runs at 11.5 nanoseconds per type-node against a hand-written check's 11.1 —
within a few percent, the code you would have written yourself. It costs more to
build, and it helps only where there is structure to unroll: for a recursive
alias or a NumPy array it stops unrolling and hands back a
:func:`~typing_validation.composition.validator`.

``benchmark/RESULTS.md`` in the repository has the full table — every case, every
mechanism, both outcomes, and the break-even points — with the machine it was
measured on.

One difference is deliberate. Because they analyse the whole type before seeing
any value, both **reject an unsupported type immediately**, where
:func:`~typing_validation.validation.validate` waits for a value to reach the
unsupported part and may never notice:

.. code-block:: python

    validator(list[Callable[[int], int]])     # UnsupportedTypeError, at once
    validate([], list[Callable[[int], int]])  # True — nothing reached it

The rest of the surface
-----------------------

.. code-block:: python

    from typing_validation import is_valid, validated, validated_iter

    is_valid([1, "a"], list[int])          # False
    validated(payload, list[int])          # returns payload, for expressions
    validated_iter(stream, Iterator[int])  # checks items as they are yielded

:func:`~typing_validation.validation.is_valid` deliberately builds no explanation: a caller who wants one calls
:func:`~typing_validation.validation.validate` and catches the exception, so a caller who wants a boolean gets one at
boolean prices.

:func:`~typing_validation.validation.validated_iter` is not a convenience wrapper. Determining the items of a one-shot
iterator consumes it, so ``Iterator[int]`` cannot check its items without destroying the value — checking each one as it
goes past is the only honest way.

Asking about a type
-------------------

Support is all-or-nothing: if any component of a type is unsupported, so is the whole type. There is no partial mode in
which the checkable parts are checked and the rest waved through, because a validation that silently skipped part of its
obligation would report success it had not earned.

:func:`~typing_validation.inspection.can_validate` answers up front:

.. code-block:: python

    >>> from typing import Callable
    >>> from typing_validation import can_validate
    >>> can_validate(list[int])
    True
    >>> can_validate(tuple[int, Callable[[int], int]])
    False

:func:`~typing_validation.inspection.inspect_type` reports the whole structure and names precisely what poisoned it, so
that "unsupported" is never opaque:

.. code-block:: python

    >>> from typing_validation import inspect_type
    >>> node = inspect_type(tuple[int, Callable[[int], int]])
    >>> [c.t for c in node.unsupported_components()]
    [typing.Callable[[int], int]]

NumPy
-----

NumPy array types are provided by an extension, which you enable by importing it:

.. code-block:: python

    import typing_validation.numpy
    from numpy.typing import NDArray

    validate(np.array([1, 2], dtype=np.uint8), NDArray[np.uint8])

The import is required rather than automatic. Enabling support merely because NumPy happened to be importable would make
the supported surface depend on transitive imports, so that :func:`~typing_validation.inspection.can_validate` answered
differently depending on whether some unrelated dependency had imported NumPy.

Extending
---------

A parametrised class can declare how its own type arguments are validated:

.. code-block:: python

    class Box[T]:
        @classmethod
        def __validate__(cls, val, args):
            return is_valid(val.item, args[0])

For classes you do not own, use :func:`~typing_validation.plugins.register_validator`.

Absent either, a parametrised class validates on its origin alone and its arguments go unchecked — a generic class does
not, in general, expose enough at runtime to determine them.

GitHub repo: https://github.com/hashberg-io/typing-validation
