# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The mechanisms that validate, as a single list to cross the corpus with.

Several independent implementations of one specification are several places to
drift, and **the drift is silent**: a mechanism that disagrees with another on
some corner returns a wrong answer with no exception and no symptom. So this
axis is not test hygiene, it is the structural member that lets the mechanisms
share no code.

Adding ``validator`` in 2.1 and ``compiled_validator`` in 2.2 means adding one
entry each to :data:`MECHANISMS` — not writing a second and third suite.
"""

from collections.abc import Callable
from typing import Any, Literal

from typing_validation import validate

__all__ = ("MECHANISMS", "MECHANISM_IDS")

Mechanism = Callable[[Any, Any], Literal[True]]
"""
A mechanism's uniform contract: given a value and a type, return :obj:`True` or
raise. ``validator(t)`` and ``compiled_validator(t)`` build a function of the
value alone, and are adapted to this shape when they land.
"""

MECHANISMS: list[Mechanism] = [validate]
"""Every mechanism that validates. All must agree on every case."""

MECHANISM_IDS: list[str] = ["validate"]
"""Names for the mechanisms, so a failure says which one drifted."""
