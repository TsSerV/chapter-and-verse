import pytest

from chapter_and_verse.db import Section
from chapter_and_verse.models import Claim, Verdict
from chapter_and_verse.verify import all_verified, check_claim, verify, words
from tests.conftest import fake_section

NOTICE = (
    "(1) The notice required to be given by an employer to terminate the contract of "
    "employment of a person who has been continuously employed for one month or more—\n"
    "(a) is not less than one week’s notice if his period of continuous employment is "
    "less than two years,\n"
    "(b) is not less than one week’s notice for each year of continuous employment if "
    "his period of continuous employment is two years or more but less than twelve years"
)
DISCLOSURE = "(1) In this Part a “ qualifying disclosure ” means any disclosure of information"


@pytest.fixture
def sections() -> list[Section]:
    return [
        fake_section("86", "Rights of employer and employee to minimum notice.", NOTICE),
        fake_section("43B", "Disclosures qualifying for protection.", DISCLOSURE),
    ]


def claim(section: str, quote: str) -> Claim:
    return Claim(text="A statement.", section=section, quote=quote)


def test_words_drops_punctuation_and_case() -> None:
    assert words("(a) is not less than one week’s notice—") == [
        "a", "is", "not", "less", "than", "one", "week", "s", "notice",
    ]  # fmt: skip


def test_a_quote_from_the_cited_section_is_verified(sections: list[Section]) -> None:
    quote = "is not less than one week’s notice"

    assert check_claim(claim("86", quote), sections) is Verdict.VERIFIED


@pytest.mark.parametrize(
    "quote",
    [
        # Straight apostrophe and capitals, where the Act has a curly one and lower case.
        "Is not less than one week's notice",
        # Across a line break, with the paragraph letter left in.
        "less than two years, (b) is not less than one week’s notice",
        # Straight quotes with no spaces, where the Act has curly quotes with spaces.
        'a "qualifying disclosure" means any disclosure',
    ],
)
def test_a_quote_is_matched_by_its_words(quote: str, sections: list[Section]) -> None:
    number = "43B" if "disclosure" in quote else "86"

    assert check_claim(claim(number, quote), sections) is Verdict.VERIFIED


def test_a_quote_that_is_not_in_the_section_is_not_found(sections: list[Section]) -> None:
    quote = "is not less than two weeks’ notice"

    assert check_claim(claim("86", quote), sections) is Verdict.QUOTE_NOT_FOUND


def test_a_quote_from_another_section_is_not_found(sections: list[Section]) -> None:
    quote = "means any disclosure of information"

    assert check_claim(claim("86", quote), sections) is Verdict.QUOTE_NOT_FOUND


def test_a_quote_must_match_whole_words(sections: list[Section]) -> None:
    # "employ" is only the start of the next word in the Act, "employment".
    quote = "to terminate the contract of employ"

    assert check_claim(claim("86", quote), sections) is Verdict.QUOTE_NOT_FOUND


def test_a_section_that_was_not_given_is_unknown(sections: list[Section]) -> None:
    quote = "is not less than one week’s notice"

    assert check_claim(claim("87", quote), sections) is Verdict.UNKNOWN_SECTION


def test_a_short_quote_is_too_short(sections: list[Section]) -> None:
    assert check_claim(claim("86", "one week’s notice"), sections) is Verdict.QUOTE_TOO_SHORT


def test_verify_keeps_each_claim_and_adds_its_verdict(sections: list[Section]) -> None:
    claims = [
        claim("86", "is not less than one week’s notice"),
        claim("99", "is not less than one week’s notice"),
    ]

    checked = verify(claims, sections)

    assert [c.verdict for c in checked] == [Verdict.VERIFIED, Verdict.UNKNOWN_SECTION]
    assert [c.quote for c in checked] == [c.quote for c in claims]
    assert verify([], sections) == []


def test_an_answer_needs_every_claim_verified(sections: list[Section]) -> None:
    good = claim("86", "is not less than one week’s notice")
    bad = claim("86", "is not less than two weeks’ notice")

    assert all_verified(verify([good, good], sections))
    assert not all_verified(verify([good, bad], sections))
    # No claims means the model found no answer in the sections.
    assert not all_verified([])
