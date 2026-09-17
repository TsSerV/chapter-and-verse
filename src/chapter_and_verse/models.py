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
    answer: str = Field(description="The answer to the question.")
    latency_ms: int = Field(ge=0, description="Time taken to build the answer.")


class HealthResponse(BaseModel):
    status: str = Field(description="Always 'ok' when the process can serve requests.")


class ErrorResponse(BaseModel):
    detail: str = Field(description="A plain message about what went wrong.")
