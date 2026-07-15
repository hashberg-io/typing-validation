# SPDX-License-Identifier: LGPL-3.0-or-later

"""Runtime validation using type hints."""

from .errors import UnsupportedTypeError, ValidationError
from .plugins import register_validator
from .validation import is_valid, validate, validated, validated_iter

__version__ = "2.0.0"

__all__ = (
    "UnsupportedTypeError",
    "ValidationError",
    "is_valid",
    "register_validator",
    "validate",
    "validated",
    "validated_iter",
)
