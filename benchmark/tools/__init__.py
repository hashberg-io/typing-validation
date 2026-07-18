# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The machinery the suite is built from.

Nothing here is run directly. ``python -m benchmark`` is the entry point, and it
is deliberately the only one: a suite with two commands grows two answers to the
same question, and the reader has no way to tell which one they are holding.

The modules divide by job rather than by subject:

- :mod:`~benchmark.tools.cases` and :mod:`~benchmark.tools.extended` — the
  corpora, which say what is measured.
- :mod:`~benchmark.tools.contenders` — the other libraries, and the tiering that
  decides which of their figures may be compared with which of ours.
- :mod:`~benchmark.tools.measure` and :mod:`~benchmark.tools.compare` — taking
  the numbers. Two modules because they cannot assume the same things: the
  mechanisms are known to agree, and a peer may not.
- :mod:`~benchmark.tools.suite` — the pipeline, which runs both of those once.
- :mod:`~benchmark.tools.tables` and :mod:`~benchmark.tools.report` — turning
  what was measured into the document.
- :mod:`~benchmark.tools.environment` and :mod:`~benchmark.tools.v1` — the
  context a figure needs to mean anything.
"""
