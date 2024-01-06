Getting Started
===============

.. _installation:

Installation
------------

You can install the latest release from PyPI as follows:

.. code-block:: console

    $ pip install --upgrade typing-validation


.. _usage:

Usage
-----

The core functionality of this library is provided by the :func:`~typing_validation.validation.validate` function:

>>> from typing_validation import validate

The :func:`~typing_validation.validation.validate` function is invoked with a value and a type as its arguments and
it returns nothing when the given value is valid for the given type:

>>> validate(12, int)
# nothing is returned => 12 is a valid int

If the value is invalid for the given type, the :func:`~typing_validation.validation.validate` function raises a :exc:`TypeError`:

>>> validate(12, str)
TypeError: Runtime validation error raised by validate(val, t), details below.
For type <class 'str'>, invalid value: 12

For nested types (e.g. parametric collection/mapping types), the full chain of validation failures is shown by the type error:

>>> validate([0, 1, "hi"], list[int])
TypeError: Runtime validation error raised by validate(val, t), details below.
For type list[int], invalid value at idx: 2
  For type <class 'int'>, invalid value: 'hi'

For union types, detailed validation failures are shown for individual union member types, where available:

>>> from typing import *
>>> validate([[0, 1, 2], {"hi": 0}], list[Union[Collection[int], dict[str, str]]])
TypeError: Runtime validation error raised by validate(val, t), details below.
For type list[typing.Union[typing.Collection[int], dict[str, str]]], invalid value at idx: 1
  For union type typing.Union[typing.Collection[int], dict[str, str]], invalid value: {'hi': 0}
    For member type typing.Collection[int], invalid value at idx: 0
      For type <class 'int'>, invalid value: 'hi'
    For member type dict[str, str], invalid value at key: 'hi'
      For type <class 'str'>, invalid value: 0

Detailed information about types supported by :func:`~typing_validation.validation.validate` is provided by
the :func:`~typing_validation.validation.can_validate` function:

>>> from typing_validation import can_validate

The :func:`~typing_validation.validation.can_validate` function is invoked with a type as its argument and it returns a
:class:`~typing_validation.validation.TypeInspector` object, containing detailed information about the structure of the type that was being validated,
including the presence of types not supported by :func:`~typing_validation.validation.validate` (wrapped into a
:class:`~typing_validation.validation.UnsupportedType`):

>>> from typing import *
>>> from typing_validation import can_validate
>>> can_validate(tuple[list[str], Union[int, float, Callable[[int], int]]])
The following type cannot be validated against:
tuple[
    list[
        str
    ],
    Union[
        int,
        float,
        UnsupportedType[
            typing.Callable[[int], int]
        ],
    ],
]

The :func:`~typing_validation.validation.validation_aliases` can be used to define set simple type aliases that can be used by
:func:`~typing_validation.validation.validate` to resolve forward references.
For example, the following snippet validates a value against a recursive type alias for JSON-like objects, using :func:`typing_validation.validation.validation_aliases` to create a
context where :func:`typing_validation.validation.validate` internally evaluates the forward reference ``"JSON"`` to the type alias ``JSON``:

>>> from typing import *
>>> from typing_validation import validate, validation_aliases
>>> JSON = Union[int, float, bool, None, str, list["JSON"], dict[str, "JSON"]]
>>> with validation_aliases(JSON=JSON):
>>>     validate([1, 2.2, {"a": ["Hello", None, {"b": True}]}], list["JSON"])


The result of :func:`~typing_validation.validation.can_validate` can be used wherever a :obj:`bool` is expected, returning :obj:`True` upon (implicit or
explicit) :obj:`bool` conversion if and only if the type can be validated:

>>> bool(can_validate(Callable[[int], int]))
False
>>> "can validate" if can_validate(Callable[[int], int]) else "cannot validate"
'cannot validate'

**Note.** Traceback information was hidden in the above examples, for clarity:
**Note.** For Python 3.7 and 3.8, use :obj:`~typing.Tuple` and :obj:`~typing.List` instead of :obj:`tuple` and :obj:`list` for the above examples.

>>> import sys
>>> sys.tracebacklimit = 0

Descriptors
-----------

The class :class:`~typing_validation.descriptor.Descriptor` can be used to create descriptors with the following features:

- static type checking for the descriptor value;
- runtime type checking;
- optional runtime validation;
- the ability to make the descriptor read-only.

The valida

.. code-block:: python

    from collections.abc import Sequence
    from typing_validation import Descriptor

    class MyClass:

        x = Descriptor(int, lambda _, x: x >= 0, readonly=True)
        y = Descriptor(Sequence[int], lambda self, y: len(y) <= self.x)

        def __init__(self, x: int, y: Sequence[int]):
            self.x = x
            self.y = y

    myobj = MyClass(3, [0, 2, 5]) # OK
    myobj.y = (0, 1)              # OK
    myobj.y = [0, 2, 4, 6]        # ValueError (lenght of y is not <= 3)
    myobj.x = 5                   # AttributeError (readonly descriptor)
    myobj.y = 5                   # TypeError (type of y is not 'Sequence')
    myobj.y = ["hi", "bye"]       # TypeError (type of y is not 'Sequence[int]')


GitHub repo: https://github.com/hashberg-io/typing-validation
