
typing-validation: Validation using Type Hints
==============================================

.. image:: https://img.shields.io/badge/python-3.7+-green.svg
    :target: https://docs.python.org/3.7/
    :alt: Python versions

.. image:: https://img.shields.io/pypi/v/typing-validation.svg
    :target: https://pypi.python.org/pypi/typing-validation/
    :alt: PyPI version

.. image:: https://img.shields.io/pypi/status/typing-validation.svg
    :target: https://pypi.python.org/pypi/typing-validation/
    :alt: PyPI status


Typing-validation is a small library to perform runtime validation of Python objects using `PEP 484 type hints <https://www.python.org/dev/peps/pep-0484/>`_.
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
    :maxdepth: 2
    :caption: Contents:

    getting-started
    api


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
