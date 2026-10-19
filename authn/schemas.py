from dataclasses import dataclass


@dataclass
class TokenPairSchema:
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
