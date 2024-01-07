# pylint: disable = missing-docstring

import sys
from typing import Any

import pytest

from typing_validation.descriptor import Descriptor


@pytest.mark.parametrize("x", [0, 10])
def test_single_descr_valid(x: Any) -> None:
    class C:
        x = Descriptor(int, lambda _, x: x >= 0)
        def __init__(self, x: int) -> None:
            self.x = x
    C(x)

@pytest.mark.parametrize("x", ["hello", 1.0])
def test_single_descr_type_error(x: Any) -> None:
    class C:
        x = Descriptor(int, lambda _, x: x >= 0)
        def __init__(self, x: int) -> None:
            self.x = x
    try:
        C("hello") # type: ignore
        assert False, f"C({x!r}) should have raised TypeError."
    except TypeError:
        pass
    try:
        c = C(0)
        c.x = x
        assert False, f"C.x = {x!r} should have raised TypeError."
    except TypeError:
        pass

@pytest.mark.parametrize("x", [-1])
def test_single_descr_value_error(x: Any) -> None:
    class C:
        x = Descriptor(int, lambda _, x: x >= 0)
        def __init__(self, x: int) -> None:
            self.x = x
    try:
        C(x)
        assert False, f"C({x!r}) should have raised ValueError."
    except ValueError:
        pass
    try:
        C(0).x = x
        assert False, f"C(0).x = {x!r} should have raised ValueError."
    except ValueError:
        pass

@pytest.mark.parametrize("x", [1])
def test_single_descr_readonly(x: Any) -> None:
    class C:
        x = Descriptor(int, lambda _, x: x >= 0, readonly=True)
        def __init__(self, x: int) -> None:
            self.x = x
    C(x)
    try:
        C(0).x = x
        assert False, f"C(0).x = {x!r} should have raised AttributeError."
    except AttributeError:
        pass

@pytest.mark.parametrize("x, y", [(0, 2), (1, 1)])
def test_two_descr_valid(x: Any, y: Any) -> None:
    class C:
        x = Descriptor(int, lambda _, x: x >= 0)
        y = Descriptor(int, lambda self, y: y >= self.x)
        def __init__(self, x: int, y: int) -> None:
            self.x = x
            self.y = y
    C(x, y)

@pytest.mark.parametrize("x, y", [(0, -1), (-1, 2), (3, 2)])
def test_two_descr_value_error(x: Any, y: Any) -> None:
    class C:
        x = Descriptor(int, lambda _, x: x >= 0)
        y = Descriptor(int, lambda self, y: y >= self.x)
        def __init__(self, x: int, y: int) -> None:
            self.x = x
            self.y = y
    try:
        C(x, y)
        assert False, f"C({x!r}, {y!r}) should have raised ValueError."
    except ValueError:
        pass
    try:
        C(x, x+1).y = y
        assert False, f"C({x!r}, {x+1!r}).y = {y!r} should have raised ValueError."
    except ValueError:
        pass

def test_getting_started_example() -> None:
    if sys.version_info[1] >= 9:

        from collections.abc import Sequence

        class MyClass:

            x = Descriptor(int, lambda _, x: x >= 0, readonly=True)
            y = Descriptor(Sequence[int], lambda self, y: len(y) <= self.x)

            def __init__(self, x: int, y: Sequence[int]):
                self.x = x
                self.y = y

        myobj = MyClass(3, [0, 2, 5]) # OK
        myobj.y = (0, 1)              # OK
        try:
            myobj.y = [0, 2, 4, 6]
            assert False, "Expected ValueError"
        except ValueError:
            pass
        try:
            myobj.x = 5
            assert False, "Expected AttributeError"
        except AttributeError:
            pass
        try:
            myobj.y = 5
            assert False, "Expected TypeError"
        except TypeError:
            pass
        try:
            myobj.y = ["hi", "bye"]
            assert False, "Expected TypeError"
        except TypeError:
            pass
