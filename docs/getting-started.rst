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
TypeError: For type <class 'str'>, invalid value: 12

For nested types (e.g. parametric collection/mapping types), the full chain of validation failures is shown by the type error:

>>> validate([0, 1, "hi"], list[int])
TypeError: For type list[int], invalid value: [0, 1, 'hi']
For type <class 'int'>, invalid value: 'hi'

For union types, detailed validation failures are shown for individual union member types, where available:

>>> from typing import *
>>> validate([[0, 1, 2], {"hi": 0}], list[Union[Collection[int], dict[str, str]]])
TypeError: For type list[typing.Union[typing.Collection[int], dict[str, str]]],
invalid value: [[0, 1, 2], {'hi': 0}]
For type typing.Union[typing.Collection[int], dict[str, str]], invalid value: {'hi': 0}
  Detailed failures for member type typing.Collection[int]:
    For type <class 'int'>, invalid value: 'hi'
  Detailed failures for member type dict[str, str]:
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
For example, the following snippet validates a value against a recursive type alias for JSON-like objects, using :func:`validation_aliases` to create a
context where :func:`validate` internally evaluates the forward reference ``"JSON"`` to the type alias ``JSON``:

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

GitHub repo: https://github.com/hashberg-io/typing-validation
