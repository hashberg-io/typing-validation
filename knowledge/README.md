# Knowledge

Curated design and reference documents for `typing-validation`.

- [DESIGN.md](DESIGN.md) — the architecture: the mechanisms that validate values against type hints, how they are separated, and why.
- [TYPES.md](TYPES.md) — the catalogue of supported type forms: what validation checks for each, what it deliberately does not check, and why.
- [GENERIC-ARGUMENTS.md](GENERIC-ARGUMENTS.md) — why a generic class validates on its origin alone, what the record actually says about that, and `__validate__` as a candidate for the one case the runtime cannot answer.

The first two are deliberately separable. `TYPES.md` specifies *what* validation means and is the authority the mechanisms answer to; `DESIGN.md` covers *how* the machinery implements it. The type surface can be revised without touching the architecture, and vice versa.

`GENERIC-ARGUMENTS.md` sits beside them rather than under either: it argues a position outward, at the ecosystem, and settles nothing on its own. Where it and `TYPES.md` appear to disagree about what a generic means, `TYPES.md` is the authority and the disagreement is the point being argued.
