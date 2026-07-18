# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The other libraries, and what it means to compare against them.

The suite's existing baselines are internal: ``hand-written`` is aspirational and
``v1`` is history. Neither says where the library sits in its own ecosystem, and
that is the question a peer review asks.

**The tiering is the finding, not the preamble.** Runtime type-checking is not one
job that several libraries do at different speeds. It is at least three jobs, and
the timing figures are only meaningful within a tier:

- :attr:`Tier.EXACT` — asks the same question and does the same work: *is this
  value, in its entirety, of this type?* Answers without touching the value. Only
  these numbers are a like-for-like race with ``validate``.

- :attr:`Tier.REBUILDING` — same accept/reject semantics once coercion is
  disabled, but returns a **new object** rather than a verdict. Measured with
  coercion off so the semantics line up; the allocation cannot be turned off, so
  the figures carry a handicap that is inherent, not incidental. Read them as an
  upper bound on the cost of the question, never as a like-for-like loss.

- :attr:`Tier.SAMPLING` — does **not** do the same work. Checks O(1) items of a
  container regardless of size, and so returns ``True`` for values that are not
  of the type. Timing these against ``validate`` on a thousand-element list races
  one ``isinstance`` against a thousand and reports the ratio as a speed
  difference. That number would be an artifact of the corpus, and the faster the
  library looked, the less it had checked. They are listed, and excluded from the
  race, and *why* is the point.

The tier is established by measurement, not by reputation: :func:`audit` runs the
probes that place each library, and its output is reported alongside the timings
so the placement can be checked rather than believed.
"""

import enum
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as _dist_version
from typing import Any, Callable, final

__all__ = ("Tier", "Usage", "Contender", "contenders", "audit", "AuditRow")


class Usage(enum.Enum):
    """
    How a library is *used*, which decides which mechanism it may be raced against.

    Orthogonal to :class:`Tier`. Tier says whether two libraries answer the same
    question; usage says whether they are being asked it the same way. Racing a
    prepared validator against a function that re-analyses the type per call
    measures the API you chose, not the library.
    """

    AD_HOC = "ad-hoc"
    """Type passed per call, analysed per call. Comparable with ``validate``."""

    PREPARED = "prepared"
    """Type analysed once into a reusable callable. Comparable with ``validator``
    and ``compiled_validator``."""


class Tier(enum.Enum):
    """What a library's figure can honestly be compared against."""

    EXACT = "exact"
    """Same question, same work, no allocation. Comparable with ``validate``."""

    REBUILDING = "rebuilding"
    """Same verdict, but constructs a new value. Comparable with a handicap."""

    SAMPLING = "sampling"
    """Checks a sample. Not comparable at any size, and excluded from the race."""


@final
@dataclass(frozen=True, slots=True)
class Contender:
    """One library, and how to ask it the question this suite asks."""

    name: str
    """What to call it in the report."""

    tier: Tier
    """Which comparisons its numbers may appear in."""

    version: str
    """What was measured, so the figure can be reproduced."""

    build: Callable[[Any], Callable[[Any], Any]] | None
    """
    Analyse a type once, returning something callable per value.

    :obj:`None` when the library has no build step to amortise, which is itself
    a fact worth reporting: it is the difference between ``validate`` and
    ``validator``.
    """

    check: Callable[[Any, Any], bool]
    """Ask the question directly, without a prepared validator."""

    usage: "Usage" = Usage.AD_HOC
    """Which mechanism's table this contender belongs in."""

    note: str = ""
    """The caveat a reader needs before trusting the number."""


def _version(dist: str, /) -> str:
    """
    The installed version, from package metadata rather than an attribute.

    ``__version__`` is a convention, not a guarantee: trycast, typeguard,
    typedload and cattrs all omit it, and reporting ``"?"`` for four of eleven
    libraries would make the table unreproducible.
    """
    try:
        return _dist_version(dist)
    except PackageNotFoundError:  # pragma: no cover
        return "?"


def _bool(fn: Callable[[Any], Any], /) -> Callable[[Any], bool]:
    """Turn a raises-on-failure API into a predicate, discarding the value."""

    def run(val: Any) -> bool:
        try:
            fn(val)
        except Exception:
            return False
        return True

    return run


def _typing_validation() -> list[Contender]:
    try:
        from typing_validation import compiled_validator, is_valid, validator
    except ImportError:  # pragma: no cover
        return []
    v = _version("typing-validation")

    def via(make: Callable[[Any], Callable[[Any], Any]], /) -> Any:
        """
        Route `check` through the prepared validator.

        `check` is the un-prepared path, used to settle support and
        verdicts. For the two prepared mechanisms it must go *through the
        prepared validator*. Delegate all three to `is_valid` instead and
        the validator and compiled rows time `validate` while reporting a
        build cost for machinery they never call — three rows differing
        only by that build column, and nothing to say they are wrong.
        """

        def check(val: Any, t: Any) -> bool:
            try:
                return bool(make(t)(val))
            except Exception:
                return False

        return check

    return [
        Contender(
            "typing-validation (validate)",
            Tier.EXACT,
            v,
            None,
            lambda val, t: bool(is_valid(val, t)),
            usage=Usage.AD_HOC,
        ),
        Contender(
            "typing-validation (validator)",
            Tier.EXACT,
            v,
            lambda t: validator(t),
            via(validator),
            usage=Usage.PREPARED,
        ),
        Contender(
            "typing-validation (compiled)",
            Tier.EXACT,
            v,
            lambda t: compiled_validator(t),
            via(compiled_validator),
            usage=Usage.PREPARED,
        ),
    ]


def _trycast() -> list[Contender]:
    """
    The one true peer: same question, same work, verdict only.

    PEP 747 files ``trycast.isassignable`` in the same category as
    ``beartype.is_bearable`` and ``typeguard.check_type`` — a type predicate —
    but of the three it is the only one that actually inspects the whole value,
    which is what makes it the only one whose figure races ``validate`` fairly.
    """
    try:
        import trycast
    except ImportError:
        return []
    version = _version("trycast")
    return [
        Contender(
            "trycast",
            Tier.EXACT,
            version,
            None,
            lambda val, t: bool(trycast.isassignable(val, t)),
            note="no build step to amortise",
        )
    ]


def _typeguard() -> list[Contender]:
    """
    Comparable only with ``ALL_ITEMS``, which is not its default.

    ``check_type`` samples the first item of a container by default, so out of
    the box it belongs in :attr:`Tier.SAMPLING`. The strategy is a **per-call
    keyword**, not the module-level ``config`` object — setting the latter leaves
    the default in force and produces a flat line that looks like a sampling
    library beating an exact one by three orders of magnitude.
    """
    try:
        import typeguard
        from typeguard import CollectionCheckStrategy
    except ImportError:
        return []
    version = _version("typeguard")
    every = CollectionCheckStrategy.ALL_ITEMS

    def check(val: Any, t: Any) -> bool:
        try:
            typeguard.check_type(val, t, collection_check_strategy=every)
        except Exception:
            return False
        return True

    return [
        Contender(
            "typeguard (ALL_ITEMS)",
            Tier.EXACT,
            version,
            None,
            check,
            note="non-default: default FIRST_ITEM samples",
        )
    ]


def _typeguard_default() -> list[Contender]:
    try:
        import typeguard
    except ImportError:
        return []
    version = _version("typeguard")

    def check(val: Any, t: Any) -> bool:
        try:
            typeguard.check_type(val, t)
        except Exception:
            return False
        return True

    return [
        Contender(
            "typeguard (default)",
            Tier.SAMPLING,
            version,
            None,
            check,
            note="FIRST_ITEM: accepts invalid values",
        )
    ]


def _beartype() -> list[Contender]:
    """
    The fastest figure here, and the one most easily misread.

    ``is_bearable`` is O(1) by design: it checks a random item per nesting level,
    which is a deliberate and well-argued trade, not a defect. But it means the
    library answers a different question, and no configuration changes that ---
    ``BeartypeStrategy.On``, the linear strategy, is documented in beartype's own
    docstring as *"currently unimplemented"*, and passing it silently returns the
    O(1) answer rather than failing.
    """
    try:
        import beartype
        from beartype.door import is_bearable
        from beartype.door import TypeHint
    except ImportError:
        return []
    version = _version("beartype")

    def prepared(t: Any) -> Callable[[Any], Any]:
        hint = TypeHint(t)
        return lambda v: hint.is_bearable(v)

    def check_prepared(val: Any, t: Any) -> bool:
        try:
            return bool(TypeHint(t).is_bearable(val))
        except Exception:
            return False

    return [
        Contender(
            "beartype (is_bearable)",
            Tier.SAMPLING,
            version,
            None,
            lambda val, t: bool(is_bearable(val, t)),
            usage=Usage.AD_HOC,
            note="O(1) by design; On strategy unimplemented",
        ),
        Contender(
            "beartype (TypeHint)",
            Tier.SAMPLING,
            version,
            prepared,
            check_prepared,
            usage=Usage.PREPARED,
            note="O(1) by design; hint built once",
        ),
    ]


def _pydantic() -> list[Contender]:
    """
    Strict mode aligns the verdict; nothing aligns the allocation.

    ``TypeAdapter`` is PEP 747's *converter* pattern, and the build/call split is
    real, so it is the fairest available comparison for ``validator`` --- but it
    returns a rebuilt value.
    """
    try:
        import pydantic
    except ImportError:
        return []
    version = pydantic.VERSION
    strict = pydantic.ConfigDict(strict=True)

    def build(t: Any) -> Callable[[Any], Any]:
        # TypedDict, NamedTuple, dataclasses and BaseModel carry their own
        # config, and pydantic refuses a `config=` argument for them rather than
        # silently ignoring it. Passing one anyway raises PydanticUserError,
        # which reads like "pydantic cannot express TypedDict" when it is really
        # this harness misusing the API. Strictness comes from the call instead.
        try:
            adapter = pydantic.TypeAdapter(t, config=strict)
        except pydantic.errors.PydanticUserError:
            adapter = pydantic.TypeAdapter(t)
            return _bool(lambda val: adapter.validate_python(val, strict=True))
        return _bool(adapter.validate_python)

    def check(val: Any, t: Any) -> bool:
        return bool(build(t)(val))

    return [
        Contender(
            "pydantic (strict)",
            Tier.REBUILDING,
            version,
            build,
            check,
            usage=Usage.PREPARED,
            note="strict=True; TypeAdapter built once; returns a new object",
        )
    ]


def _msgspec() -> list[Contender]:
    """
    Ad-hoc only, and that is the library rather than the harness.

    ``convert`` re-analyses the type on every call --- measurably, against a
    value that never changes: an empty list costs about 0.13 µs more per level of
    nesting and 0.37 µs more per union member, all of it type analysis. Its
    prepared cousins, ``json.Decoder`` and ``msgpack.Decoder``, hoist exactly
    that work, and both take **bytes**: there is no in-memory ``Decoder``, and
    ``msgspec.inspect`` returns a description with no callable in it. So there is
    nothing for a caller to hoist, and no prepared row to register.

    Registering one anyway --- ``lambda t: (lambda v: convert(v, t))`` --- would
    report a build cost of nothing for machinery that never ran, and a per-call
    figure identical to the ad-hoc row. That is the mistake ``via`` above records
    having already been made once with this library's own mechanisms, and it is
    not worth making again in a peer's favour.

    Its figure therefore carries per-call analysis that ``validator``'s does not,
    which is the honest comparison: ``validate`` also analyses per call, and that
    is the row msgspec appears beside.
    """
    try:
        import msgspec
    except ImportError:
        return []
    version = _version("msgspec")

    def check(val: Any, t: Any) -> bool:
        try:
            msgspec.convert(val, t, strict=True)
        except Exception:
            return False
        return True

    return [
        Contender(
            "msgspec (convert, strict)",
            Tier.REBUILDING,
            version,
            None,
            check,
            note="strict=True; re-analyses the type per call, and offers no API to hoist it; returns a new object",
        )
    ]


def _typedload() -> list[Contender]:
    """
    Two modes, and the difference between them is a factor of five.

    ``typedload.load`` builds a fresh ``Loader`` per call; a hoisted
    ``Loader`` is the library's own documented way to avoid that. Timing only
    the module-level function against a prepared ``validator`` would report an
    API misuse as a library's speed, so both are listed and each is raced only
    against the mechanism it resembles.
    """
    try:
        import typedload
        import typedload.dataloader
    except ImportError:
        return []
    version = _version("typedload")
    loader = typedload.dataloader.Loader(basiccast=False)

    def check(val: Any, t: Any) -> bool:
        try:
            typedload.load(val, t, basiccast=False)
        except Exception:
            return False
        return True

    def check_prepared(val: Any, t: Any) -> bool:
        try:
            loader.load(val, t)
        except Exception:
            return False
        return True

    return [
        Contender(
            "typedload (load)",
            Tier.REBUILDING,
            version,
            None,
            check,
            usage=Usage.AD_HOC,
            note="basiccast=False; builds a Loader per call",
        ),
        Contender(
            "typedload (Loader)",
            Tier.REBUILDING,
            version,
            lambda t: (lambda v: loader.load(v, t)),
            check_prepared,
            usage=Usage.PREPARED,
            note="hoisted Loader; returns a new object",
        ),
    ]


def _cattrs() -> list[Contender]:
    """
    Included as a converter, and made non-coercing the way cattrs intends.

    A bare ``Converter`` casts ``["1"]`` to ``[1]``, and no constructor argument
    stops it: ``detailed_validation`` governs how much an error says and
    ``forbid_extra_keys`` governs extra keys, and neither is strictness. That is
    easy to mistake for cattrs having no non-coercing mode, and it is not one.
    Coercion lives in per-class structure hooks that call ``cl(obj)``, so
    overriding those hooks is what turns it off --- and that is cattrs' own idiom
    rather than something devised here. Its ``preconf`` converters are built
    exactly this way, down to a shipped ``validate_datetime`` hook whose body is
    the one below, and ``configure_union_passthrough`` is documented as the way
    to *validate and pass through* a union rather than convert it.

    Configuring it costs cattrs roughly 15% and is still the right measurement.
    :attr:`Tier.REBUILDING` is defined as the same verdict *once coercion is
    disabled*, and every other library in that tier is measured with its
    alignment on: pydantic ``strict=True``, msgspec ``strict=True``, typedload
    ``basiccast=False``. Left bare, cattrs would post a faster figure for an
    easier question, and be recorded as incapable of one it can do.

    What stays unaligned afterwards is reach rather than coercion --- a
    structured union like ``list[int] | list[str]`` wants a tag in the payload,
    and a recursive alias has no hook at all --- and both show up as rejections,
    so the figures stay honest about what was checked.
    """
    try:
        import cattrs
        from cattrs.strategies import configure_union_passthrough
    except ImportError:
        return []
    version = _version("cattrs")
    converter = cattrs.Converter()
    for cls in (int, float, str, bytes, bool):

        def hook(val: Any, _: Any, _cls: type = cls) -> Any:
            if not isinstance(val, _cls):
                raise ValueError(f"{val!r} is not a {_cls.__name__}")
            return val

        converter.register_structure_hook(cls, hook)
    # `accept_ints_as_floats=False` to match `validate`, which does not
    # implement the numeric tower: an `int` is not a `float` here.
    configure_union_passthrough(
        int | float | str | bytes | bool | None,
        converter,
        accept_ints_as_floats=False,
    )

    def check(val: Any, t: Any) -> bool:
        try:
            converter.structure(val, t)
        except Exception:
            return False
        return True

    return [
        Contender(
            "cattrs",
            Tier.REBUILDING,
            version,
            None,
            check,
            note="hooks disable coercion; returns a new object",
        )
    ]


def contenders() -> list[Contender]:
    """Every library that could be loaded, in tier order."""
    found = (
        _typing_validation()
        + _trycast()
        + [c for c in _typeguard() if c.tier is Tier.EXACT]
        + _typeguard_default()
        + _beartype()
        + _pydantic()
        + _msgspec()
        + _typedload()
        + _cattrs()
    )
    order = {Tier.EXACT: 0, Tier.REBUILDING: 1, Tier.SAMPLING: 2}
    return sorted(found, key=lambda c: order[c.tier])


@final
@dataclass(frozen=True, slots=True)
class AuditRow:
    """What one library did to the probes that place it in a tier."""

    name: str
    tier: Tier
    version: str
    catches_deep: bool | None
    """Rejects a large list whose *last* item is wrong. False => samples."""

    rejects_coercible: bool | None
    """Rejects ``["1","2"]`` for ``list[int]``. False => coerces."""

    note: str


def audit(contenders_: list[Contender], /) -> list[AuditRow]:
    """
    Re-derive every tier by probing, so the classification can be checked.

    Two probes settle it. A list of a thousand valid items with one invalid item
    **last** separates checking from sampling: anything that returns ``True`` did
    not look. A list of numeric strings against ``list[int]`` separates checking
    from coercing.
    """
    deep_bad: list[Any] = list(range(999)) + ["X"]
    coercible: list[Any] = ["1", "2", "3"]
    rows: list[AuditRow] = []
    for c in contenders_:
        try:
            catches = not c.check(deep_bad, list[int])
        except Exception:
            catches = None
        try:
            rejects = not c.check(coercible, list[int])
        except Exception:
            rejects = None
        rows.append(
            AuditRow(c.name, c.tier, c.version, catches, rejects, c.note)
        )
    return rows
