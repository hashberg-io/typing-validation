# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Loading v1 alongside v2, so the two can be compared in one process.

v1 lives on the ``main`` branch and is not installed anywhere. Rather than ask
for a second environment, this extracts it from git into a temporary directory
and imports it under a name of its own — which works because v1 still runs on
3.14, and because the two versions share no module state.
"""

import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import cast

_V1_REF = "main"
"""Where v1 lives. The trunk still holds 1.2.11."""


def load_v1() -> ModuleType | None:
    """
    v1's module, or :obj:`None` if it could not be loaded.

    Returning :obj:`None` rather than raising is deliberate: the comparison is
    the most important number here, but it is not worth failing the whole suite
    over a missing git ref.
    """
    if "typing_validation_v1" in sys.modules:
        return sys.modules["typing_validation_v1"]
    root = Path(tempfile.mkdtemp(prefix="typing-validation-v1-"))
    try:
        archive = subprocess.run(
            ["git", "archive", _V1_REF, "typing_validation"],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["tar", "-x", "-C", str(root)], input=archive.stdout, check=True
        )
    except subprocess.CalledProcessError, FileNotFoundError:
        return None
    (root / "typing_validation").rename(root / "typing_validation_v1")
    sys.path.insert(0, str(root))
    try:
        import typing_validation_v1  # type: ignore[import-not-found]

        return cast(ModuleType, typing_validation_v1)
    except ImportError:
        return None
