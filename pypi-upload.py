#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-3.0-or-later

"""Build one or more tagged releases and upload them to PyPI.

Uses ``uv`` to build and ``twine`` (run through ``uvx``) to validate and upload,
so it needs only ``uv`` and ``git`` on the PATH. Run it from the project root,
naming the tags to release:

    python pypi-upload.py v2.1.0
    python pypi-upload.py v2.1.0 v2.2.0

Each tag is built from a detached worktree of that tag, never from the checked-out
working tree, so an edited, half-merged or simply stale checkout cannot reach PyPI.
Naming the tags also means releasing a version other than the one checked out no
longer requires checking it out, and several versions can go up in one run.

Two guards back that up: the version recorded in each built artefact must match the
tag it came from, and only artefacts built by this run are handed to twine, so a
stray file left in ``dist/`` cannot be uploaded by accident.

Existing releases are skipped, so re-running after a partial upload is safe.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DIST = Path("dist")
TAG = re.compile(r"^v(?P<version>\d+\.\d+\.\d+.*)$")
USAGE = "usage: python pypi-upload.py <tag> [<tag> ...]   (e.g. v2.1.0)"


def run(*cmd: str) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def tag_version(tag: str) -> str:
    """The version a tag promises: ``v2.1.0`` -> ``2.1.0``."""
    match = TAG.match(tag)
    if match is None:
        sys.exit(
            f"error: {tag!r} is not a version tag of the form 'v<major>.<minor>.<patch>'."
        )
    return match.group("version")


def artefact_version(artefact: Path) -> str:
    """The version recorded in a built artefact's filename."""
    name = artefact.name
    if name.endswith(".whl"):
        return name.split("-")[1]
    return name[: -len(".tar.gz")].rsplit("-", 1)[1]


def check_tag_exists(tag: str) -> None:
    # refs/tags/ spelled in full: a branch sharing the tag's name is otherwise
    # ambiguous, and git resolves the ambiguity with a warning rather than an error.
    ref = f"refs/tags/{tag}"
    found = subprocess.run(
        ("git", "rev-parse", "--verify", "--quiet", ref), capture_output=True
    )
    if found.returncode != 0:
        sys.exit(f"error: no tag {tag!r} in this repository.")


def build(tag: str) -> list[Path]:
    """Build a tag in its own worktree, returning the artefacts it produced."""
    version = tag_version(tag)
    check_tag_exists(tag)
    before = set(DIST.glob("*"))
    with tempfile.TemporaryDirectory(prefix="pypi-upload-") as tmp:
        tree = Path(tmp) / tag
        run("git", "worktree", "add", "--detach", str(tree), f"refs/tags/{tag}")
        try:
            run("uv", "build", "--out-dir", str(DIST.resolve()), str(tree))
        finally:
            run("git", "worktree", "remove", "--force", str(tree))
    artefacts = sorted(
        p for p in set(DIST.glob("*")) - before if p.suffix in (".whl", ".gz")
    )
    if not artefacts:
        sys.exit(f"error: building {tag} produced no artefacts in {DIST}/.")
    for artefact in artefacts:
        built = artefact_version(artefact)
        if built != version:
            sys.exit(
                f"error: {tag} builds version {built}, not {version}.\n"
                f"       The tagged tree declares a version its tag does not match."
            )
    return artefacts


def main(argv: list[str]) -> int:
    if not argv or {"-h", "--help"} & set(argv):
        sys.exit(USAGE)
    for tool in ("uv", "git"):
        if shutil.which(tool) is None:
            sys.exit(f"error: {tool!r} is not on the PATH.")
    tags = list(dict.fromkeys(argv))
    # Every tag is checked before dist/ is touched: a typo must not cost the artefacts
    # already sitting there.
    for tag in tags:
        tag_version(tag)
        check_tag_exists(tag)
    # Start from a clean dist/ so stale artefacts are never left lying about. Only
    # what this run builds is uploaded regardless, but a tidy dist/ is easier to trust.
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    artefacts: list[Path] = []
    for tag in tags:
        artefacts.extend(build(tag))
    paths = [str(p) for p in artefacts]
    run("uvx", "twine", "check", *paths)
    run("uvx", "twine", "upload", "--skip-existing", *paths)
    print(f"\nuploaded {', '.join(tags)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
