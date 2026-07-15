#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-3.0-or-later

"""Build the distribution and upload it to PyPI.

Cross-platform replacement for the old ``pypi-upload.bat``. Uses ``uv`` to build
and ``twine`` (run through ``uvx``) to validate and upload, so it needs only
``uv`` on the PATH. Run it from the project root:

    python pypi-upload.py

Existing releases are skipped, so re-running after a partial upload is safe.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

DIST = Path("dist")


def run(*cmd: str) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> int:
    if shutil.which("uv") is None:
        sys.exit("error: 'uv' is not on the PATH (see https://docs.astral.sh/uv/).")
    # Start from a clean dist/ so stale artefacts are never uploaded.
    if DIST.exists():
        shutil.rmtree(DIST)
    run("uv", "build")
    # Select only build artefacts: uv also drops a dist/.gitignore that must not
    # be passed to twine.
    artefacts = sorted(str(p) for pat in ("*.whl", "*.tar.gz") for p in DIST.glob(pat))
    if not artefacts:
        sys.exit("error: no artefacts were produced in dist/.")
    run("uvx", "twine", "check", *artefacts)
    run("uvx", "twine", "upload", "--skip-existing", *artefacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
