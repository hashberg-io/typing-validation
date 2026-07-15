# Knowledge

Curated design and reference documents for `typing-validation`.

- [DESIGN.md](DESIGN.md) — the architecture: the mechanisms that validate values against type hints, how they are separated, and why.
- [TYPES.md](TYPES.md) — the catalogue of supported type forms: what validation checks for each, what it deliberately does not check, and why.

The two are deliberately separable. `TYPES.md` specifies *what* validation means and is the authority the mechanisms answer to; `DESIGN.md` covers *how* the machinery implements it. The type surface can be revised without touching the architecture, and vice versa.
