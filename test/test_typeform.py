# SPDX-License-Identifier: LGPL-3.0-or-later

"""
That ``validated`` accepts the type forms people actually validate against.

``type[T]`` is what a validation library reaches for and is wrong: a union, a
literal and :obj:`None` are type *forms* rather than classes, so it rejects
``validated(x, int | str)`` — about the most ordinary thing anyone would write.
PEP 747's ``TypeForm[T]`` is the form of that distinction.

Adopting it costs nothing. From 3.15 it is :obj:`typing.TypeForm`; on 3.14 the
import is type-checking-only, typeshed carries the stub so mypy needs no package
installed, and the docs read annotations as strings. These tests hold that
bargain to its terms on both.
"""

import pathlib
import subprocess
import sys
import textwrap
import tomllib
import typing

import pytest

from typing_validation import validated


def _mypy(source: str, tmp_path: pathlib.Path, python_version: str, /) -> str:
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
            "--python-version",
            python_version,
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

    @pytest.mark.parametrize("python_version", ["3.14", "3.15"])
    def test_every_form_is_accepted_and_inferred(
        self, tmp_path: pathlib.Path, python_version: str
    ) -> None:
        out = _mypy(ACCEPTS, tmp_path, python_version)
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
    ``TypeForm`` comes from the standard library on 3.15 and is imported under
    ``TYPE_CHECKING`` on 3.14, which is what keeps this a zero-dependency
    library. If any of these stops holding, the trade has changed and the import
    should be reconsidered.
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


def test_the_annotations_resolve_from_3_15() -> None:
    """
    From 3.15 the annotations of :func:`validated` resolve to
    :obj:`typing.TypeForm`. On 3.14 the name exists only for the type checker,
    so resolving them raises :class:`NameError`, which is the one cost of the
    arrangement there.
    """
    if sys.version_info >= (3, 15):
        hints = typing.get_type_hints(validated)
        assert typing.get_origin(hints["t"]) is typing.TypeForm
    else:
        with pytest.raises(NameError):
            typing.get_type_hints(validated)
