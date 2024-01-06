
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

.. image:: http://www.mypy-lang.org/static/mypy_badge.svg
    :target: https://github.com/python/mypy
    :alt: Checked with Mypy

.. image:: https://readthedocs.org/projects/typing-validation/badge/?version=latest
    :target: https://typing-validation.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status

.. image:: https://github.com/hashberg-io/typing-validation/actions/workflows/python-pytest.yml/badge.svg
    :target: https://github.com/hashberg-io/typing-validation/actions/workflows/python-pytest.yml
    :alt: Python package status

.. image:: https://img.shields.io/badge/readme%20style-standard-brightgreen.svg?style=flat-square
    :target: https://github.com/RichardLitt/standard-readme
    :alt: standard-readme compliant

Typing-validation is a small library to perform runtime validation of Python objects using `PEP 484 type hints <https://www.python.org/dev/peps/pep-0484/>`_.

.. contents::


Install
-------

You can install the latest release from `PyPI <https://pypi.org/project/multiformats/>`_ as follows:

.. code-block::

    pip install --upgrade typing-validation


Usage
-----

The core functionality of this library is provided by the `validate` function:


>>> from typing_validation import validate

The `validate` function is invoked with a value and a type as its arguments and it returns nothing when the given value is valid for the given type:

>>> validate(12, int)
# nothing is returned => 12 is a valid int

If the value is invalid for the given type, the `validate` function raises a `TypeError`:

>>> validate(12, str)
TypeError: Runtime validation error raised by validate(val, t), details below.
For type <class 'str'>, invalid value: 12

For nested types (e.g. parametric collection/mapping types), the full chain of validation failures is shown by the type error:

>>> validate([0, 1, "hi"], list[int])
TypeError: Runtime validation error raised by validate(val, t), details below.
For type list[int], invalid value at idx: 2
  For type <class 'int'>, invalid value: 'hi'


API
---

For the full API documentation, see https://typing-validation.readthedocs.io/


Contributing
------------

Please see `<CONTRIBUTING.md>`_.


License
-------

`MIT © Hashberg Ltd. <LICENSE>`_
