# SPDX-License-Identifier: LGPL-3.0-or-later

"""
That the cross-references in docstrings actually resolve.

A clean Sphinx build is not evidence of this, which is the whole reason these
exist. ``skip_missing_references`` in ``docs/conf.py`` silences the warning for a
name by rendering it as **plain, unclickable text** — so a reference that names a
path autodoc does not document looks perfect in the build log and is dead on the
page. That is exactly what happened: every docstring wrote
``~typing_validation.validate``, which is how you *import* it and not where it is
*documented*, and the whole set went out broken.

These tests read the built HTML instead, because the rendered link is the thing
the reader clicks.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).parent.parent

BUILT = ROOT / "docs" / "_build" / "html" / "api"

if not BUILT.is_dir():
    # Skipped here rather than inside the parametrisation below, which pytest
    # evaluates while *collecting* and where a skip aborts the whole run. These
    # need built HTML, so they run in the docs job; the test job has none.
    pytest.skip(
        "docs not built; run `cd docs && python make-api.py && make html`",
        allow_module_level=True,
    )

XREF = re.compile(
    r'(<a class="reference (?:internal|external)"[^>]*>)?'
    r'<code class="[^"]*xref[^"]*"[^>]*><span class="pre">([A-Za-z_][\w.]*)</span>'
)

ALLOWED_DEAD = {
    # A type parameter of a generic function, which has no page to link to.
    "T",
    # PEP 747, imported under TYPE_CHECKING to keep the library dependency-free.
    "TypeForm",
}


def _pages() -> list[pathlib.Path]:
    return sorted(BUILT.glob("*.html"))


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.stem)
def test_every_cross_reference_is_clickable(page: pathlib.Path) -> None:
    text = re.sub(r"\s+", " ", page.read_text())
    dead = {
        name
        for linked, name in XREF.findall(text)
        if not linked and name not in ALLOWED_DEAD
    }
    assert not dead, (
        f"{page.name} renders these as plain text rather than links: "
        f"{sorted(dead)}. Either the reference names a path autodoc does not "
        f"document, or the role is wrong, or it needs a type_aliases entry."
    )


def test_the_skip_list_stays_small() -> None:
    """
    Every entry in ``skip_missing_references`` is a dead link on the page.

    It reads like a warning filter and is not: it is a list of references the
    project has given up on. Adding to it should feel expensive.
    """
    conf = (ROOT / "docs" / "conf.py").read_text()
    body = conf[
        conf.index("skip_missing_references") : conf.index("# Anything else")
    ]
    entries = re.findall(r'^\s+"([^"]+)",', body, re.MULTILINE)
    assert set(entries) == ALLOWED_DEAD, (
        f"docs/conf.py skips {sorted(set(entries))}, this test expects "
        f"{sorted(ALLOWED_DEAD)}. If a name genuinely cannot resolve, add it to "
        f"both, with the reason."
    )
