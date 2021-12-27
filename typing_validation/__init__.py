"""
    Top-level imports for this module:

    - module :mod:`typing_validation.validation`

        - function :func:`~typing_validation.validation.validate`

    - module :mod:`typing_validation.validation_failure`

        - function :func:`~typing_validation.validation_failure.get_validation_failure`
        - function :func:`~typing_validation.validation_failure.latest_validation_failure`
"""

__version__ = "0.0.1"

from .validation import validate
from .validation_failure import get_validation_failure, latest_validation_failure

# re-export all encodings and functions.
__all__ = [
    "validate",
    "get_validation_failure",
    "latest_validation_failure"
]
