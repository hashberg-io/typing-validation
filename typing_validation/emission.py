# SPDX-License-Identifier: LGPL-3.0-or-later

"""
Emitting Python source specialised to one type, compiling it, and returning the
result.

The goal is code equivalent to what a competent programmer would write by hand
for that one type: flat, unrolled, with the ``isinstance`` checks inlined and no
per-node dispatch of any kind. The cost is compile latency, paid once,
deliberately, by a caller who has decided it is worth it.

**Why unrolling is safe, and where it stops.** Unrolled loops nest once per level
of the *type*, and for an acyclic type that bounds the value: ``list[int]``
against a value nested twenty thousand deep fails its ``isinstance`` at level two
and never descends. So there is no recursion to overflow, and the emitted code can
be exactly the nested loops one would write.

A cycle removes that bound — a recursive alias accepts a value of any depth — and
unrolling it does not terminate anyway. So unrolling stops at a back-edge, and at
every other boundary the emitted code calls into the composed validator, whose
driver is a loop and therefore safe at any depth. That is the same
de-optimisation a plugin forces, for the same reason: you cannot inline code you
do not have.
"""

from collections.abc import Callable, Collection, Mapping
from typing import Any, Literal, Union, get_args, get_origin

from .composition import Runner, Validator, runner_for, validator
from .diagnosis import diagnose
from .errors import UnsupportedTypeError, ValidationError
from .nodes import TypeForm, TypeNode, node_for

__all__ = ("compiled_validator",)

_MAX_NESTING = 16
"""
How deep the emitted code will nest before it calls instead.

A second dimension the node budget cannot see, and a hard one, because it guards
two compile-time limits at once. Each container the emitter unrolls opens a
``for`` loop, and **CPython refuses more than twenty statically nested blocks**,
raising *"too many statically nested blocks"* the moment a twenty-first loop
nests inside the twentieth. Each ``TypedDict`` field opens an ``if``, and CPython
caps indentation at a hundred levels instead. The loop limit is the tighter of
the two by far, and it is the one the benchmark suite hit, by having a
hundred-deep chain of lists — which, left alone, unrolls into source that will
not compile at all.

A nesting level is at least as deep as either, so bounding it bounds both, and
the twenty-block limit is what the ceiling is really set against. Sixteen is
under it with room to spare and far over anything real. Past it, the composed
validator takes over, which costs nothing that matters: a type that deep spends
its time descending rather than dispatching.
"""

_INLINE_BUDGET = 256
"""
How many checks an emitted function will unroll before it calls instead, counted
with multiplicity.

Set from the benchmarks rather than from argument, and they argued with the
question more than with the answer.

The expectation was a trade: unrolling destroys the sharing that makes
composition cheap, so somewhere there had to be a cliff. There is no cliff. Cost
is **linear** in the emitted size — sixty wide dictionaries unroll to fourteen
thousand lines and forty milliseconds — and unrolling *always* wins on speed,
repaying its build cost within about one value for ``list[int]``, twenty-eight
for ``dict[str, int]``, eighty-five for a twenty-fold shared sub-type, and four
hundred and sixty-five for a forty-field ``TypedDict``. For a mechanism whose
entire premise is very many values against a fixed type, every one of those is
nothing.

So the budget is generous, and its job is smaller than expected: it stops a
monstrous type from spending tens of milliseconds in the compiler by surprise,
and degrades it to the composed validator instead. It is a guard rail, not a
tuning knob.

It must be counted with multiplicity, which was the first version's real mistake.
See :func:`_unrolled_size`.
"""


def compiled_validator(t: Any, /) -> Validator:
    """
    A validation function specialised to one type, compiled from source.

    Same contract as :func:`~typing_validation.validation.validate` and
    :func:`~typing_validation.composition.validator`, and the same verdict on
    every value. It costs more to build than either and less to run, so it is
    worth it when the same type is validated very many times::

        check = compiled_validator(list[int])
        for payload in payloads:
            check(payload)

    Like :func:`~typing_validation.composition.validator`, and for the same
    reason, it refuses an unsupported type at construction rather than waiting
    for a value to reach the unsupported part.

    :raises UnsupportedTypeError: if the type, or any component of it, is not one
        this library can validate against.
    """
    node = node_for(t)
    if not node.supported:
        culprits = node.unsupported_components()
        raise UnsupportedTypeError(t, culprits[0].reason if culprits else None)
    if _is_pure_call_out(node):
        # Nothing here to compile: the whole body would be one call into the
        # composed validator, because the type is a cycle, a plugin, a literal, a
        # structured union, or anything else with no source to unroll. So this
        # *is* the composed validator, rather than the composed validator behind
        # a function call — which is what it was, and which measured slower than
        # asking for the composed validator directly.
        return validator(t)
    check = _compile(node)

    def run(val: Any) -> Literal[True]:
        if check(val):
            return True
        raise ValidationError(val, t, diagnose(val, t))

    return run


def source_for(t: Any, /) -> str:
    """
    The source that :func:`compiled_validator` would compile for a type.

    Exposed because emitted code that cannot be read cannot be reviewed, and
    because a test that asserts on the *source* can say things about the shape —
    that a loop was unrolled, that a boundary became a call — which a test that
    only runs the result cannot.
    """
    return _emit(node_for(t)).source


class _Emission:
    """One function's worth of emitted source, and what it needs to run."""

    __slots__ = ("source", "globals", "_names")

    def __init__(self) -> None:
        self.source = ""
        self.globals: dict[str, Any] = {}
        self._names = 0

    def constant(self, value: Any, hint: str, /) -> str:
        """
        Bind a value into the emitted function's globals, and name it.

        A type can never be a code constant — ``co_consts`` admits only
        ``None``, numbers, strings, bytes, tuples, frozensets and code — so
        ``int`` cannot be written into the source as itself. It becomes a global
        the compiled function loads by name.
        """
        self._names += 1
        name = f"_{hint}{self._names}"
        self.globals[name] = value
        return name


def _unrolled_size(node: TypeNode, limit: int, /) -> int:
    """
    How many checks unrolling this node would emit, counted **with
    multiplicity**.

    Not the number of distinct nodes, which is the mistake this replaced. The
    graph is a DAG over distinct sub-types — that is what makes composition cheap
    — and unrolling flattens it back into a tree, so a sub-type mentioned twenty
    times is emitted twenty times. Counting the DAG made every budget from 8 to
    4096 produce byte-identical source, because a tuple of twenty identical
    dictionaries has six distinct nodes and a hundred emitted ones.

    Stops counting at ``limit``: the answer is only ever compared against the
    budget, and a pathological type is exactly the one whose true size is not
    worth computing.
    """
    total = 0
    stack = [node]
    while stack:
        current = stack.pop()
        total += 1
        if total > limit:
            return total
        stack.extend(current.children)
    return total


def _cyclic(node: TypeNode, /) -> bool:
    """
    Whether a cycle is reachable from a node.

    A cycle is what removes the bound the type otherwise puts on the value's
    depth, and it is the one thing unrolling cannot do at all.
    """
    grey: set[int] = set()
    done: set[int] = set()
    stack: list[tuple[TypeNode, bool]] = [(node, False)]
    while stack:
        current, leaving = stack.pop()
        if leaving:
            grey.discard(id(current))
            done.add(id(current))
            continue
        if id(current) in done:
            continue
        if id(current) in grey:
            return True
        grey.add(id(current))
        stack.append((current, True))
        for child in current.children:
            stack.append((child, False))
    return False


def _emit(node: TypeNode, /) -> _Emission:
    out = _Emission()
    body = _lines(node, "_v", out, depth=0, budget=_INLINE_BUDGET)
    out.source = (
        "def _check(_v):\n"
        + "\n".join(f"    {line}" for line in body)
        + "\n    return True\n"
    )
    return out


def _compile(node: TypeNode, /) -> Runner:
    out = _emit(node)
    namespace: dict[str, Any] = dict(out.globals)
    exec(out.source, namespace)
    return namespace["_check"]  # type: ignore[no-any-return]


def _is_pure_call_out(node: TypeNode, /) -> bool:
    """Whether emitting this node would produce nothing but a call."""
    probe = _Emission()
    return _lines(
        node, "_v", probe, depth=0, budget=_INLINE_BUDGET
    ) == _call_out(node, "_v", _Emission())


def _call_out(node: TypeNode, var: str, out: _Emission, /) -> list[str]:
    """
    Hand this node to the composed validator and be done with it.

    Reached at a cycle, at a plugin, and anywhere the budget runs out. All three
    are the same situation — code that cannot or should not be unrolled here —
    and the composed closure is correct, already built, and drives its own loop,
    so it is safe at any depth.
    """
    # Through the driver, not the raw check: a check that can descend pushes onto
    # a stack that something has to drain, and handing it a throwaway list loses
    # the work silently — reporting valid for a value that is not. That bug was
    # written here once and caught by a recursive alias whose bad item sat behind
    # a push.
    name = out.constant(runner_for(node), "call")
    return [f"if not {name}({var}):", "    return False"]


def _lines(
    node: TypeNode, var: str, out: _Emission, /, *, depth: int, budget: int
) -> list[str]:
    """
    Emit the statements that check ``var`` against this node, or bail to a call.

    Returns lines that ``return False`` on failure and fall through on success,
    which is what lets a caller concatenate them without threading a flag.
    """
    if (
        depth >= _MAX_NESTING
        or _cyclic(node)
        or _unrolled_size(node, budget) > budget
    ):
        return _call_out(node, var, out)
    form = node.form
    t = node.t
    if form is TypeForm.ANY:
        return []
    if form is TypeForm.NONE:
        return [f"if {var} is not None:", "    return False"]
    if form in _WRAPPERS:
        if not node.children:
            return []
        return _lines(node.children[0], var, out, depth=depth, budget=budget)
    if form is TypeForm.CLASS or form is TypeForm.PROTOCOL:
        origin = get_origin(t)
        name = out.constant(t if origin is None else origin, "cls")
        return [f"if not isinstance({var}, {name}):", "    return False"]
    if form is TypeForm.UNION:
        members = t.__args__
        if all(type(member) is type for member in members):
            name = out.constant(members, "members")
            return [f"if not isinstance({var}, {name}):", "    return False"]
        return _call_out(node, var, out)
    if form is TypeForm.COLLECTION:
        return _loop(node, var, out, get_origin(t), depth, budget)
    if form is TypeForm.MAPPING:
        return _mapping(node, var, out, get_origin(t), depth, budget)
    if form is TypeForm.TUPLE:
        return _tuple(node, var, out, get_args(t), depth, budget)
    if form is TypeForm.TYPED_DICT:
        return _typed_dict(node, var, out, t, depth, budget)
    if form is TypeForm.NAMED_TUPLE:
        return _named_tuple(node, var, out, t, depth, budget)
    # Literals, Type[T], iterators, generic classes, plugins and anything else:
    # nothing to unroll, or nothing we have the source for.
    return _call_out(node, var, out)


_WRAPPERS = frozenset(
    {TypeForm.ALIAS, TypeForm.ANNOTATED, TypeForm.NEW_TYPE, TypeForm.TYPE_VAR}
)


def _loop(
    node: TypeNode,
    var: str,
    out: _Emission,
    origin: Any,
    depth: int,
    budget: int,
    /,
) -> list[str]:
    name = out.constant(origin, "cls")
    lines = [f"if not isinstance({var}, {name}):", "    return False"]
    if not node.children:
        return lines
    item = f"_i{depth}"
    inner = _lines(node.children[0], item, out, depth=depth + 1, budget=budget)
    if not inner:
        return lines
    lines.append(f"for {item} in {var}:")
    lines.extend(f"    {line}" for line in inner)
    return lines


def _mapping(
    node: TypeNode,
    var: str,
    out: _Emission,
    origin: Any,
    depth: int,
    budget: int,
    /,
) -> list[str]:
    name = out.constant(origin, "cls")
    lines = [f"if not isinstance({var}, {name}):", "    return False"]
    if not node.children:
        return lines
    key, value = f"_k{depth}", f"_w{depth}"
    inner = _lines(node.children[0], key, out, depth=depth + 1, budget=budget)
    inner += _lines(
        node.children[1], value, out, depth=depth + 1, budget=budget
    )
    if not inner:
        return lines
    lines.append(f"for {key}, {value} in {var}.items():")
    lines.extend(f"    {line}" for line in inner)
    return lines


def _tuple(
    node: TypeNode,
    var: str,
    out: _Emission,
    args: tuple[Any, ...],
    depth: int,
    budget: int,
    /,
) -> list[str]:
    lines = [f"if not isinstance({var}, tuple):", "    return False"]
    if not args:
        return lines + [f"if {var}:", "    return False"]
    if len(args) == 2 and args[1] is Ellipsis:
        item = f"_i{depth}"
        inner = _lines(
            node.children[0], item, out, depth=depth + 1, budget=budget
        )
        if not inner:
            return lines
        lines.append(f"for {item} in {var}:")
        lines.extend(f"    {line}" for line in inner)
        return lines
    lines += [f"if len({var}) != {len(args)}:", "    return False"]
    for i, child in enumerate(node.children):
        # Fixed-length, so each position is unrolled by index — which is the
        # whole point, and what a hand-written check would do.
        lines += _lines(
            child, f"{var}[{i}]", out, depth=depth + 1, budget=budget
        )
    return lines


def _typed_dict(
    node: TypeNode,
    var: str,
    out: _Emission,
    t: Any,
    depth: int,
    budget: int,
    /,
) -> list[str]:
    mapping = out.constant(Mapping, "cls")
    lines = [f"if not isinstance({var}, {mapping}):", "    return False"]
    for key in sorted(t.__required_keys__):
        lines += [f"if {key!r} not in {var}:", "    return False"]
    for label, child in zip(node.labels or (), node.children):
        item = f"_f{depth}"
        inner = _lines(child, item, out, depth=depth + 1, budget=budget)
        if not inner:
            continue
        # Absent optional keys are not checked, and absent required ones have
        # already failed above.
        lines.append(f"{item} = {var}.get({label!r}, _MISSING)")
        lines.append(f"if {item} is not _MISSING:")
        lines.extend(f"    {line}" for line in inner)
    out.globals["_MISSING"] = _MISSING
    return lines


_MISSING = object()


def _named_tuple(
    node: TypeNode,
    var: str,
    out: _Emission,
    t: Any,
    depth: int,
    budget: int,
    /,
) -> list[str]:
    name = out.constant(t, "cls")
    lines = [f"if not isinstance({var}, {name}):", "    return False"]
    for label, child in zip(node.labels or (), node.children):
        lines += _lines(
            child, f"{var}.{label}", out, depth=depth + 1, budget=budget
        )
    return lines
