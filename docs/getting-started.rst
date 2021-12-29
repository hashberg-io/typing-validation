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

**Note.** Traceback information was hidden in the above examples, for clarity:

>>> import sys
>>> sys.tracebacklimit = 0

GitHub repo: https://github.com/hashberg-io/typing-validation
