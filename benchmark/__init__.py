# SPDX-License-Identifier: LGPL-3.0-or-later

"""
The benchmark suite.

**This is a deliverable, not a diagnostic.** The entire justification for having
three validators is performance. Without measurement that justification is a
hypothesis and the extra mechanisms are unexplained complexity, so the suite is
what converts the design's central claim into something falsifiable.

Run it with ``python -m benchmark``. It writes one document,
``benchmark/REPORT.md``, holding both halves of the question: whether the three
mechanisms earn their complexity, and where the library sits among its peers.
The machinery is in :mod:`benchmark.tools`; the synthesis a reader should start
from is ``benchmark/PEER-COMPARISON.md``, which is written rather than generated.

The peer half needs libraries that are not installed by default::

    uv sync --group peers

Without them the suite still runs and the report says so, rather than failing.
"""
