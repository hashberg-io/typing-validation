# SPDX-License-Identifier: LGPL-3.0-or-later

"""
What machine produced a number.

Captured because a figure without its context is unreadable six months later, and
because the only thing worse than no benchmark is one whose numbers are quietly
compared across different machines.
"""

import platform
import sys
from typing import Any


def environment() -> dict[str, Any]:
    """The Python build, the machine, and the versions in play."""
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "build": " ".join(platform.python_build()),
        "compiler": platform.python_compiler(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "free_threading": not getattr(sys, "_is_gil_enabled", lambda: True)(),
    }


def describe(env: dict[str, Any]) -> str:
    return "\n".join(f"  {key:16} {value}" for key, value in env.items())
