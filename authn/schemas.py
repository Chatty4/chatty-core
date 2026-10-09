from pydantic import BaseModel


class TokenPairSchema(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
