import time

import jwt
import pytest

from authn.services import AuthnService, _private_key
from shared.exceptions import Unauthorized


@pytest.mark.parametrize(
    "claims",
    [{"sub": "7f1e0a9e-0000-4000-8000-000000000000"}, {"exp": int(time.time()) + 60}],
    ids=["no exp", "no sub"],
)
def test_token_without_required_claim_is_rejected(claims):
    token = jwt.encode(claims, _private_key(), algorithm="RS256")

    with pytest.raises(Unauthorized):
        AuthnService.decode_access_token(token)
