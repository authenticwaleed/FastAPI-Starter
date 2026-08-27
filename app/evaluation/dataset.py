"""The questions the assistant is measured against, and what is expected.

A file rather than a fixture in a test, because the plan asks for a
dataset built from real, anonymised pilot questions -- which means it is
edited by whoever is running the pilot, grows every week, and is read by
people who do not write Python.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATASET = Path(__file__).resolve().parent / "cases.json"


@dataclass(frozen=True)
class Case:
    """One question, and what a good answer to it looks like.

    The four things the plan asks each case to define: what a right answer
    contains, which source it has to come from, whether the assistant
    should answer at all, and whether it should hand over.

    `should_answer` and `should_handoff` are both here rather than one
    being the negation of the other, because a third outcome exists: a
    question the assistant is meant to decline *without* pulling a person
    in. Keeping them separate is what lets the dataset say so.
    """

    id: str
    question: str
    should_answer: bool
    should_handoff: bool = False
    # Substrings a right answer contains. Deliberately crude: a semantic
    # grader is another model, another cost, and another thing that can be
    # wrong in a way nobody notices. A phrase check is dumb and honest.
    expected_phrases: list[str] = field(default_factory=list)
    # Substrings that make an answer wrong. Where the hallucinations the
    # plan asks to track are recorded: a case that once produced an
    # invented delivery time gets that time added here, and any future
    # prompt that reproduces it fails.
    forbidden_phrases: list[str] = field(default_factory=list)
    # A phrase that must appear in the knowledge the retrieval hands over,
    # which is what "required source" means in practice -- the answer has
    # to have been grounded in the right passage, not merely be correct by
    # luck.
    required_source: str | None = None
    # What the knowledge base must contain for this case to be meaningful.
    # Held with the case so the dataset is self-contained: a case whose
    # supporting document lives somewhere else is a case that silently
    # stops testing anything when that document moves.
    knowledge: list[str] = field(default_factory=list)
    notes: str | None = None


def load_cases(path: Path | None = None) -> list[Case]:
    """Read the dataset, refusing anything malformed.

    Loudly rather than skipping: a case with a typo in a field name would
    otherwise quietly stop being evaluated, and an evaluation that is
    silently measuring less than it says is worse than one that fails.
    """
    raw: Any = json.loads((path or DATASET).read_text(encoding="utf-8"))

    if not isinstance(raw, list):
        raise ValueError("The evaluation dataset must be a list of cases")

    cases = [Case(**item) for item in raw]
    seen = {case.id for case in cases}

    if len(seen) != len(cases):
        raise ValueError("Two evaluation cases share an id")

    return cases
