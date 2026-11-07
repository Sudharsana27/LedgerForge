from pydantic import BaseModel, ConfigDict, Field


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=72)


class AccessTokenOut(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
