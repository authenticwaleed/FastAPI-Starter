"""Measuring whether the assistant is actually useful.

The plan's instruction is not to judge quality by reading a few demos. So
this is a dataset of cases with expectations attached, a runner that puts
each one through the real pipeline, and a report of the metrics the plan
names -- keyed by prompt version, so two versions of the instructions can
be compared rather than argued about.
"""

from app.evaluation.dataset import Case, load_cases
from app.evaluation.runner import Outcome, Report, run

__all__ = ["Case", "Outcome", "Report", "load_cases", "run"]
