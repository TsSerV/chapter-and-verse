from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    # Strip spaces first, so "   " fails the length check.
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(
        min_length=3,
        max_length=2000,
        description="A question about UK legislation, 3 to 2000 characters.",
        examples=["When did the Data Protection Act 2018 come into force?"],
    )


class Source(BaseModel):
    """A section of an Act that the answer was written from."""

    model_config = ConfigDict(from_attributes=True)

    act: str = Field(
        description="The Act, as type/year/number.", examples=["ukpga/1996/18"]
    )
    number: str = Field(description="The section number.", examples=["94"])
    title: str
    uri: str = Field(description="The section on legislation.gov.uk.")
    valid_from: date = Field(
        description="This version of the text is in force from here."
    )


class Verdict(StrEnum):
    """What the check of one claim found."""

    VERIFIED = "verified"
    # The claim cites a section the model was not given.
    UNKNOWN_SECTION = "unknown_section"
    QUOTE_TOO_SHORT = "quote_too_short"
    # The words are not in the cited section, in that order.
    QUOTE_NOT_FOUND = "quote_not_found"


class Claim(BaseModel):
    """One statement of an answer, with the words of the Act it rests on."""

    text: str = Field(description="One statement, in plain words.")
    section: str = Field(
        description="The number of the section it comes from.", examples=["86"]
    )
    quote: str = Field(description="Words copied from that section.")


class CheckedClaim(Claim):
    verdict: Verdict = Field(description="What the check of the quote found.")


class AskResponse(BaseModel):
    answer_id: int = Field(description="Use it to read the answer back later.")
    answer: str = Field(
        description="The answer, with the section cited after each claim."
    )
    sources: list[Source] = Field(description="The sections given to the model.")
    latency_ms: int = Field(ge=0, description="Time taken to build the answer.")


class AnswerRecord(BaseModel):
    # Built from an Answer row with AnswerRecord.model_validate(row).
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: str = Field(description="Matches the X-Request-ID header and the logs.")
    question: str
    answer: str
    sources: list[Source] = Field(description="The sections given to the model.")
    model: str = Field(description="The Claude model that wrote the answer.")
    latency_ms: int = Field(ge=0, description="Time taken to build the answer.")
    created_at: datetime = Field(description="When the answer was stored.")


class HealthResponse(BaseModel):
    status: str = Field(description="Always 'ok' when the process can serve requests.")


class ErrorResponse(BaseModel):
    detail: str = Field(description="A plain message about what went wrong.")
