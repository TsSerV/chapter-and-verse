from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(
        min_length=1,
        description="A question about UK legislation.",
        examples=["When did the Data Protection Act 2018 come into force?"],
    )


class AskResponse(BaseModel):
    answer: str = Field(description="The answer to the question.")
    latency_ms: int = Field(ge=0, description="Time taken to build the answer.")
