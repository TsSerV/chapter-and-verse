from datetime import datetime

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


class AskResponse(BaseModel):
    answer_id: int = Field(description="Use it to read the answer back later.")
    answer: str = Field(description="The answer to the question.")
    latency_ms: int = Field(ge=0, description="Time taken to build the answer.")


class AnswerRecord(BaseModel):
    # Built from an Answer row with AnswerRecord.model_validate(row).
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: str = Field(description="Matches the X-Request-ID header and the logs.")
    question: str
    answer: str
    model: str = Field(description="The Claude model that wrote the answer.")
    latency_ms: int = Field(ge=0, description="Time taken to build the answer.")
    created_at: datetime = Field(description="When the answer was stored.")


class HealthResponse(BaseModel):
    status: str = Field(description="Always 'ok' when the process can serve requests.")


class ErrorResponse(BaseModel):
    detail: str = Field(description="A plain message about what went wrong.")
