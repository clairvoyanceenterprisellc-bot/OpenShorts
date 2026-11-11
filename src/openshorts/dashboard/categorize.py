"""First-pass category tagging.

Audio-loudness detection alone can tell you a moment was *intense* — it
can't reliably tell "funny" apart from "tips and tricks" without actually
understanding what's being said. So the honest MVP behavior is:

  - the loudest highlights in a session (top `BEST_MOMENT_PERCENTILE`) get
    auto-tagged "Best Moments"
  - everything else lands in "Unsorted" for you to tag by hand

"Funny Clips" and "Tips & Tricks" are manual-tag categories for now. A
speech-to-text pass (e.g. faster-whisper) is the natural next step to
auto-detect those from what's actually being said — see README.
"""

from __future__ import annotations

import numpy as np

BEST_MOMENTS = "best_moments"
FUNNY = "funny"
TIPS_TRICKS = "tips_tricks"
UNSORTED = "unsorted"

CATEGORY_LABELS = {
    BEST_MOMENTS: "Best Moments",
    FUNNY: "Funny Clips",
    TIPS_TRICKS: "Tips & Tricks",
    UNSORTED: "Unsorted",
}

ALL_CATEGORIES = tuple(CATEGORY_LABELS)

BEST_MOMENT_PERCENTILE = 70.0  # top 30% of a session's highlight scores


def assign_categories(scores: list[float]) -> list[str]:
    """Given the highlight scores for one session, return a parallel list of categories."""
    if not scores:
        return []
    if len(scores) < 3:
        # Too few data points for a percentile split to mean anything —
        # the single/double loudest moment(s) of the session are the highlight.
        threshold = min(scores)
    else:
        threshold = float(np.percentile(scores, BEST_MOMENT_PERCENTILE))
    return [BEST_MOMENTS if s >= threshold else UNSORTED for s in scores]
