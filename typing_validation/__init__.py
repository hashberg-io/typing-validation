"""
    Runtime validation using type hints.
"""

__version__ = "1.2.11"

from .inspector import TypeInspector, UnsupportedType
from .validation import (
    validate,
    inspect_type,
    can_validate,
    validation_aliases,
    validated,
    validated_iter,
    is_valid,
)
from .validation_failure import (
    get_validation_failure,
    latest_validation_failure,
)

# re-export all encodings and functions.
__all__ = [
    "validate",
    "inspect_type",
    "can_validate",
    "validation_aliases",
    "is_valid",
    "validated",
    "validated_iter",
    "TypeInspector",
    "UnsupportedType",
    "get_validation_failure",
    "latest_validation_failure",
]
