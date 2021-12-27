
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

.. image:: https://github.com/hashberg-io/typing-validation/actions/workflows/python-pytest.yml/badge.svg
    :target: https://github.com/hashberg-io/typing-validation/actions/workflows/python-pytest.yml
    :alt: Python package status

.. image:: https://img.shields.io/badge/readme%20style-standard-brightgreen.svg?style=flat-square
    :target: https://github.com/RichardLitt/standard-readme
    :alt: standard-readme compliant


Table of Contents
-----------------

- :ref:`install`
- :ref:`usage`
- :ref:`api`
- [Contributing](#contributing)
- [License](#license)


.. _install:

Install
-------

You can install the latest release from PyPI as follows:

.. code-block:: console

    $ pip install --upgrade typing-validation


.. _usage:

Usage
-----

The core functionality of this library is provided by the `validate` function:


>>> from typing_validation import validate

The `validate` function is invoked with a value and a type as its arguments and it returns nothing when the given value is valid for the given type:

>>> validate(12, int)
# nothing is returned => 12 is a valid int

If the value is invalid for the given type, the `validate` function raises a `TypeError`:

>>> validate(12, str)
TypeError: For type <class 'str'>, invalid value: 12

For nested types (e.g. parametric collection/mapping types), the full chain of validation failures is shown by the type error:

>>> validate([0, 1, "hi"], list[int])
TypeError: For type list[int], invalid value: [0, 1, 'hi']
  For type <class 'int'>, invalid value: 'hi'


.. _api:

API
---

For the full API documentation, see 


.. _contributing:

Contributing
------------

Please see :doc:`CONTRIBUTING.md`.


.. _contributing:

License
-------

MIT © Hashberg Ltd. See :doc:`LICENSE`.
