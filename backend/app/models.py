from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

KST = timezone(timedelta(hours=9))
Metric = Literal["cpu", "memory"]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")]


def now_iso():
    return datetime.now(KST).isoformat(timespec="seconds")


class DataInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date: AwareDatetime
    value: float = Field(ge=0, le=100, allow_inf_nan=False)
    memo: str = Field(default="", max_length=500)
    metric: Metric
    host: Literal["demo-01"] = "demo-01"

    @field_validator("date")
    @classmethod
    def normalize_date(cls, value):
        return value.astimezone(KST)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(KST))


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=100)
    messages: list[Message] = Field(min_length=1, max_length=80)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: Identifier | None = None
