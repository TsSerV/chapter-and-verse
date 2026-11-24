"""Check that each claim of an answer quotes the section it cites."""

import re

from chapter_and_verse.db import Section
from chapter_and_verse.models import CheckedClaim, Claim, Verdict

# A shorter quote would match almost any section.
MIN_QUOTE_WORDS = 5


def words(text: str) -> list[str]:
    # Letters and digits only, in lower case. The Act has curly quotes and long dashes,
    # and a model copies them in its own way.
    return re.findall(r"\w+", text.casefold())


def check_claim(claim: Claim, sections: list[Section]) -> Verdict:
    by_number = {section.number: section for section in sections}
    section = by_number.get(claim.section.strip())
    if section is None:
        return Verdict.UNKNOWN_SECTION
    quote = words(claim.quote)
    if len(quote) < MIN_QUOTE_WORDS:
        return Verdict.QUOTE_TOO_SHORT
    # Spaces at both ends, so "employ" does not match inside "employee".
    if f" {' '.join(quote)} " not in f" {' '.join(words(section.text))} ":
        return Verdict.QUOTE_NOT_FOUND
    return Verdict.VERIFIED


def verify(claims: list[Claim], sections: list[Section]) -> list[CheckedClaim]:
    return [
        CheckedClaim(**claim.model_dump(), verdict=check_claim(claim, sections))
        for claim in claims
    ]


def all_verified(checked: list[CheckedClaim]) -> bool:
    # No claims is not an answer. One claim that fails spoils the whole answer.
    return bool(checked) and all(c.verdict is Verdict.VERIFIED for c in checked)
