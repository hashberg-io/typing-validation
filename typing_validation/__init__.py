# SPDX-License-Identifier: LGPL-3.0-or-later

"""Runtime validation using type hints."""

from .errors import UnsupportedTypeError, ValidationError
from .inspection import (
    can_validate,
    clear_cache,
    forget_type,
    inspect_type,
    scoped_cache,
)
from .nodes import TypeForm, TypeNode
from .plugins import register_validator
from .validation import is_valid, validate, validated, validated_iter

__version__ = "2.0.0"

__all__ = (
    "TypeForm",
    "TypeNode",
    "UnsupportedTypeError",
    "ValidationError",
    "can_validate",
    "clear_cache",
    "forget_type",
    "inspect_type",
    "is_valid",
    "register_validator",
    "scoped_cache",
    "validate",
    "validated",
    "validated_iter",
)
