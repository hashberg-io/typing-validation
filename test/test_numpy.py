# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Tests for the NumPy plugin.

NumPy is the first client of the extension API, and a punishing one: dtype
unions, shape tuples, and an ``NDArray`` that is a PEP 695 alias over a
parametrised origin. If the API can express NumPy, it can express what users will
bring to it.
"""

import subprocess
import sys
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

import typing_validation.numpy  # noqa: F401  (importing it is what enables it)
from typing_validation import (
    UnsupportedTypeError,
    ValidationError,
    can_validate,
    inspect_type,
    is_valid,
    validate,
)
from typing_validation.nodes import TypeForm

VECTOR = np.array([1, 2], dtype=np.uint8)
FLOATS = np.array([1.5], dtype=np.float32)
MATRIX = np.array([[1, 2], [3, 4]], dtype=np.uint8)


class TestDtype:

    def test_a_matching_dtype(self) -> None:
        assert validate(VECTOR, NDArray[np.uint8]) is True

    def test_a_mismatched_dtype(self) -> None:
        with pytest.raises(ValidationError):
            validate(FLOATS, NDArray[np.uint8])

    def test_an_abstract_dtype_accepts_a_concrete_one(self) -> None:
        # issubdtype, not issubclass: NDArray[np.integer] accepts uint8.
        assert validate(VECTOR, NDArray[np.integer]) is True

    def test_an_abstract_dtype_still_rejects(self) -> None:
        with pytest.raises(ValidationError):
            validate(FLOATS, NDArray[np.integer])

    def test_a_union_of_dtypes(self) -> None:
        t = NDArray[np.uint8 | np.float32]
        assert validate(VECTOR, t) is True
        assert validate(FLOATS, t) is True

    def test_a_union_of_dtypes_still_rejects(self) -> None:
        with pytest.raises(ValidationError):
            validate(
                np.array([1], dtype=np.int64), NDArray[np.uint8 | np.float32]
            )

    def test_any_dtype(self) -> None:
        assert validate(VECTOR, NDArray[Any]) is True
        assert validate(FLOATS, NDArray[Any]) is True

    def test_a_nonsense_dtype_is_unsupported(self) -> None:
        with pytest.raises(UnsupportedTypeError):
            validate(VECTOR, np.ndarray[tuple[int], np.dtype[str]])  # type: ignore[type-var]


class TestShape:
    """
    The shape is handed straight back to the core.

    It is an ordinary type and ``.shape`` is an ordinary tuple, so there is no
    shape logic in the plugin at all — which is the point.
    """

    def test_any_shape(self) -> None:
        assert validate(VECTOR, NDArray[np.uint8]) is True
        assert validate(MATRIX, NDArray[np.uint8]) is True

    def test_a_fixed_rank(self) -> None:
        t = np.ndarray[tuple[int, int], np.dtype[np.uint8]]
        assert validate(MATRIX, t) is True

    def test_the_wrong_rank(self) -> None:
        t = np.ndarray[tuple[int, int], np.dtype[np.uint8]]
        with pytest.raises(ValidationError):
            validate(VECTOR, t)

    def test_a_literal_dimension(self) -> None:
        from typing import Literal

        assert is_valid(
            MATRIX,
            np.ndarray[tuple[Literal[2], Literal[2]], np.dtype[np.uint8]],
        )
        assert not is_valid(
            MATRIX,
            np.ndarray[tuple[Literal[3], Literal[3]], np.dtype[np.uint8]],
        )


class TestNotAnArray:

    def test_a_non_array_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate([1, 2], NDArray[np.uint8])

    def test_a_scalar_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate(1, NDArray[np.uint8])


class TestStructure:

    def test_an_ndarray_type_is_a_plugin_node(self) -> None:
        node = inspect_type(np.ndarray[tuple[int, int], np.dtype[np.uint8]])
        assert node.form is TypeForm.PLUGIN

    def test_ndarray_is_reached_through_the_alias(self) -> None:
        # NDArray is a PEP 695 alias in modern NumPy, so it resolves by
        # substitution and only then lands on the plugin hook.
        node = inspect_type(NDArray[np.uint8])
        assert node.form is TypeForm.ALIAS
        assert any(n.form is TypeForm.PLUGIN for n in node.walk())

    def test_the_shape_is_a_component_and_the_dtype_is_not(self) -> None:
        # Totality must propagate through the shape, which the core validates,
        # and must not reach the dtype, which is the plugin's own specification.
        # Treating the dtype as a component would poison every array type, since
        # numpy.dtype[numpy.uint8] is a parametrised numpy class with no
        # validator of its own.
        node = inspect_type(np.ndarray[tuple[int, int], np.dtype[np.uint8]])
        assert [c.t for c in node.children] == [tuple[int, int]]

    def test_totality_propagates_through_the_shape(self) -> None:
        from typing import Callable

        t = np.ndarray.__class_getitem__(
            (tuple[Callable[[int], int]], np.dtype[np.uint8])
        )
        assert can_validate(t) is False

    def test_a_supported_array_type_can_be_validated(self) -> None:
        assert can_validate(NDArray[np.uint8]) is True


class TestExplicitImportIsRequired:
    """
    Without the import, NumPy types are unsupported, and the error says which
    import would fix it.

    Enabling automatically when NumPy happens to be importable was rejected on
    determinism grounds: the supported surface would depend on transitive
    imports, and ``can_validate`` would answer differently depending on whether
    some unrelated dependency had imported NumPy.
    """

    def test_unimported_numpy_types_are_unsupported(self) -> None:
        # A subprocess, because this process has the plugin imported already and
        # registration is global and permanent by design.
        script = (
            "import numpy as np\n"
            "from numpy.typing import NDArray\n"
            "from typing_validation import can_validate, validate\n"
            "assert can_validate(NDArray[np.uint8]) is False\n"
            "try:\n"
            "    validate(np.array([1.5]), NDArray[np.uint8])\n"
            "except Exception as e:\n"
            "    assert type(e).__name__ == 'UnsupportedTypeError', type(e)\n"
            "    assert 'typing_validation.numpy' in str(e), str(e)\n"
            "else:\n"
            "    raise AssertionError('should have raised')\n"
            "print('ok')\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True
        )
        assert out.returncode == 0, out.stderr
        assert "ok" in out.stdout

    def test_it_would_otherwise_pass_unchecked(self) -> None:
        # What the error is protecting against: validating on the origin alone
        # would report success it had not earned.
        assert isinstance(FLOATS, np.ndarray)


def test_registration_invalidates_the_cache() -> None:
    """
    Interning must never be semantically observable, and registration is the one
    thing that can change what is supported.

    A node interned before the plugin was imported records the type as
    unsupported, and would go on saying so while a cold cache said otherwise.
    """
    script = (
        "import numpy as np\n"
        "from numpy.typing import NDArray\n"
        "from typing_validation import can_validate\n"
        "assert can_validate(NDArray[np.uint8]) is False\n"
        "import typing_validation.numpy\n"
        "assert can_validate(NDArray[np.uint8]) is True, 'stale node survived'\n"
        "print('ok')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert "ok" in out.stdout
