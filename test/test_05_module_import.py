import importlib.machinery
import sys
import types

from typing import List, Optional, Sequence

import pytest


class FailMockFinder:
    def __init__(self, modules: List[str]) -> None:
        self.modules = modules

    def find_spec(
        self,
        fullname: str,
        path: Optional[Sequence[str]],
        target: Optional[types.ModuleType],
    ) -> Optional[importlib.machinery.ModuleSpec]:
        if fullname in self.modules:
            raise ModuleNotFoundError(f"No module named '{fullname}'", name=fullname)
        return None


@pytest.mark.skipif(sys.version_info < (3, 11), reason='Python <3.11 needs typing_extensions')
def test_typing_extensions_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    finder = FailMockFinder(['typing_extensions'])
    monkeypatch.setattr(sys, 'meta_path', [finder] + sys.meta_path)
    monkeypatch.delitem(sys.modules, 'typing_extensions')
    import typing_validation
