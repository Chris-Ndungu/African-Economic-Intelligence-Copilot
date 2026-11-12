"""Deterministic analysis functions.

Each function takes series already loaded by a ``DataService`` and returns
result models from :mod:`copilot_core.models`. They do no I/O, use no
randomness and import no web framework, so the same input always gives the
same answer, with or without Gemini.
"""

from copilot_core.analysis.anomaly import detect_anomalies
from copilot_core.analysis.baseline import compare_with_baseline
from copilot_core.analysis.common import AnalysisError
from copilot_core.analysis.comparison import compare_countries
from copilot_core.analysis.trend import TrendResult, analyze_trend

__all__ = [
    "AnalysisError",
    "TrendResult",
    "analyze_trend",
    "compare_countries",
    "compare_with_baseline",
    "detect_anomalies",
]
