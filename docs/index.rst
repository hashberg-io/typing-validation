
typing-validation: Validation using Type Hints
==============================================

Typing-validation is a small library to perform runtime validation of Python objects using `PEP 484 type hints <https://www.python.org/dev/peps/pep-0484/>`_.

GitHub repo: https://github.com/hashberg-io/typing-validation

If ``val`` is a value of type ``t``, the call ``validate(val, t)`` raises no error:

>>> from typing_validation import validate
>>> validate([0, 1, 2], list[int])
# no error raised => [0, 1, 2] is a value of type list[int]

If ``val`` is **not** a value of type ``t``, the call ``validate(val, t)`` raises a :exc:`TypeError`, with detailed information about validation failure(s):


>>> validate([[0, 1, 2], {"hi": 0}], list[Union[Collection[int], dict[str, str]]])
TypeError: For type list[typing.Union[typing.Collection[int], dict[str, str]]],
invalid value: [[0, 1, 2], {'hi': 0}]
For type typing.Union[typing.Collection[int], dict[str, str]], invalid value: {'hi': 0}
  Detailed failures for member type typing.Collection[int]:
    For type <class 'int'>, invalid value: 'hi'
  Detailed failures for member type dict[str, str]:
    For type <class 'str'>, invalid value: 0


.. toctree::
    :maxdepth: 3
    :caption: Contents:

    getting-started

.. include:: api-toc.rst

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
