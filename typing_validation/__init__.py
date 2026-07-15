# SPDX-License-Identifier: LGPL-3.0-or-later

"""Runtime validation using type hints."""

from .errors import UnsupportedTypeError, ValidationError

__version__ = "2.0.0"

__all__ = ("UnsupportedTypeError", "ValidationError")
