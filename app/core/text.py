"""Turning whatever a business uploaded into passages worth retrieving.

Pure functions, no database and no provider. The whole of this file is
decisions about text, which is the part of retrieval that is easiest to
get wrong quietly: a chunk split through the middle of a sentence still
embeds, still retrieves, and still produces an answer -- a worse one, for
a reason nothing reports.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass

# Characters, not tokens. Tokenising properly means either the provider's
# tokeniser or a second dependency, and the thing this number actually
# controls is "roughly a few paragraphs", which characters express well
# enough. Around 1000 characters is 200-300 tokens: big enough to carry an
# answer, small enough that a retrieved chunk is mostly about one thing.
CHUNK_SIZE = 1000

# Enough that a sentence spanning a boundary is whole in one of the two
# chunks. Without it, the answer to a question can be split across a
# boundary and neither half retrieves.
CHUNK_OVERLAP = 150

# Below this a chunk is a fragment -- a heading, a stray line after a
# split -- and embedding it mostly adds noise to retrieval.
MIN_CHUNK_LENGTH = 40

_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n\s*\n\s*")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")
# What a PDF extractor leaves behind: a word broken across a line end with
# a hyphen. Rejoined, because "ship-\nping" retrieves for neither word.
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")


@dataclass(frozen=True)
class Chunk:
    """One passage, and where in the document it came from."""

    index: int
    content: str


def normalise(raw: str) -> str:
    """Put text into the one form everything downstream sees.

    Normalising before hashing is what makes the content hash mean "the
    same knowledge" rather than "the same bytes": the same policy exported
    by two tools differs in line endings and spacing and nothing else.

    NFKC folds the typographic characters that PDFs are full of -- ligature
    forms, full-width punctuation, the several kinds of non-breaking space
    -- onto the ordinary ones, so a question typed on a phone can match a
    document set in a word processor. It is what makes the whitespace
    collapse below see one space character rather than five.
    """
    text = unicodedata.normalize("NFKC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _WHITESPACE.sub(" ", text)
    text = _TRAILING_SPACE.sub("\n", text)
    # Any run of blank lines becomes exactly one, which is what the chunker
    # then treats as a paragraph boundary.
    text = _BLANK_LINES.sub("\n\n", text)

    return text.strip()


def content_hash(normalised: str) -> str:
    """The identity of a piece of knowledge, for spotting a re-upload."""
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def chunk(normalised: str) -> list[Chunk]:
    """Split normalised text into overlapping passages.

    Boundaries are looked for in descending order of how much they mean:
    a paragraph break, then a line break, then the end of a sentence. Only
    when none of those is anywhere near the target does it cut mid-word,
    which is the case that produces a fragment nobody would recognise.
    """
    if not normalised:
        return []

    chunks: list[Chunk] = []
    start = 0
    length = len(normalised)

    while start < length:
        end = min(start + CHUNK_SIZE, length)

        if end < length:
            end = _break_before(normalised, start, end)

        piece = normalised[start:end].strip()

        if len(piece) >= MIN_CHUNK_LENGTH or (not chunks and piece):
            # The second condition keeps a document that is shorter than
            # the minimum -- a one-line FAQ answer is still knowledge.
            chunks.append(Chunk(index=len(chunks), content=piece))

        if end >= length:
            break

        # Step back by the overlap, but always forward overall: without
        # the max() a boundary found close to the start would loop.
        start = max(end - CHUNK_OVERLAP, start + 1)

    return chunks


def _break_before(text: str, start: int, end: int) -> int:
    """The most meaningful place to cut at or before `end`.

    Only looks back within the last quarter of the chunk. Further than
    that and the "boundary" is really the previous paragraph, which would
    make every chunk a fraction of its intended size.
    """
    floor = start + (CHUNK_SIZE * 3 // 4)

    for separator in ("\n\n", "\n", ". ", "? ", "! "):
        found = text.rfind(separator, floor, end)

        if found != -1:
            return found + len(separator)

    space = text.rfind(" ", floor, end)

    return space + 1 if space != -1 else end
