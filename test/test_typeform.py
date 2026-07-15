# SPDX-License-Identifier: LGPL-3.0-or-later

"""
That ``validated`` accepts the type forms people actually validate against.

``type[T]`` is what a validation library reaches for and is wrong: a union, a
literal and :obj:`None` are type *forms* rather than classes, so it rejects
``validated(x, int | str)`` — about the most ordinary thing anyone would write.
PEP 747's ``TypeForm[T]`` is the form of that distinction.

Adopting it costs nothing: the import is type-checking-only, typeshed carries the
stub so mypy needs no package installed, and the docs read annotations as
strings. These tests hold that bargain to its terms.
"""

import pathlib
import subprocess
import sys
import textwrap
import tomllib
import typing

import pytest

from typing_validation import validated


def _mypy(source: str, tmp_path: pathlib.Path, /) -> str:
    # A file rather than `-c`, because the project's own mypy config names the
    # files to check and mypy refuses both at once. `--no-site-packages` is
    # deliberately absent: resolving typing_extensions from typeshed is the whole
    # point, and it must keep working without the package present.
    script = tmp_path / "check_typeform.py"
    script.write_text(textwrap.dedent(source))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--no-incremental",
            "--no-error-summary",
            str(script),
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


ACCEPTS = """
    from typing import Iterator, Literal, TypedDict
    from typing_validation import validated

    class Movie(TypedDict):
        title: str

    reveal_type(validated(1, int))
    reveal_type(validated([1], list[int]))
    reveal_type(validated(1, int | str))
    reveal_type(validated("a", Literal["a", "b"]))
    reveal_type(validated({"title": "x"}, Movie))
    reveal_type(validated(None, None))
"""


class TestStaticInference:

    def test_every_form_is_accepted_and_inferred(
        self, tmp_path: pathlib.Path
    ) -> None:
        out = _mypy(ACCEPTS, tmp_path)
        assert "error:" not in out, out
        for expected in (
            'Revealed type is "int"',
            'Revealed type is "list[int]"',
            'Revealed type is "int | str"',
            "Literal['a'] | Literal['b']",
            'Revealed type is "None"',
        ):
            assert expected in out, f"{expected!r} missing from:\n{out}"


class TestTheBargain:
    """
    ``TypeForm`` is imported under ``TYPE_CHECKING``, which is what keeps this a
    zero-dependency library. If any of these stops holding, the trade has changed
    and the import should be reconsidered.
    """

    def test_typing_extensions_is_not_imported_at_runtime(self) -> None:
        out = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, typing_validation;"
                "print('typing_extensions' in sys.modules)",
            ],
            capture_output=True,
            text=True,
        )
        assert out.stdout.strip() == "False", out.stderr

    def test_the_library_has_no_install_requirements(self) -> None:
        with open("pyproject.toml", "rb") as f:
            assert tomllib.load(f)["project"]["dependencies"] == []

    def test_validated_still_works_at_runtime(self) -> None:
        assert validated(1, int) == 1
        assert validated([1], list[int]) == [1]


def test_typing_dot_typeform_has_not_landed_yet() -> None:
    """
    When this fails, 3.15 has arrived with PEP 747 in the standard library, and
    the ``TYPE_CHECKING`` import should become an ordinary one — which also
    removes the one cost of the current arrangement, that ``get_type_hints`` on
    these functions raises ``NameError``.
    """
    if hasattr(typing, "TypeForm"):  # pragma: no cover
        pytest.fail(
            "typing.TypeForm exists: import it directly in validation.py, drop "
            "the TYPE_CHECKING guard, and drop TypeForm from "
            "skip_missing_references in docs/conf.py."
        )
