"""Error codes from the contract (chatty-infra/docs/api-core.md and api-internal.md).

Add a code to the contract first, then here.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    # Every endpoint
    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    USER_INACTIVE = "user_inactive"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
    INVALID_CURSOR = "invalid_cursor"

    # 400
    NOT_ALLOWED_FOR_DM = "not_allowed_for_dm"
    CANNOT_ARCHIVE_DEFAULT = "cannot_archive_default"
    CANNOT_LEAVE_DM = "cannot_leave_dm"
    USER_NOT_IN_TEAM = "user_not_in_team"
    FILE_TOO_LARGE = "file_too_large"
    TYPE_NOT_ALLOWED = "type_not_allowed"
    UPLOAD_MISSING = "upload_missing"
    UPLOAD_MISMATCH = "upload_mismatch"
    USE_CHATTY_CHAT = "use_chatty_chat"
    INVALID_FILE = "invalid_file"
    WRONG_PASSWORD = "wrong_password"
    WRONG_PURPOSE = "wrong_purpose"
    WRONG_TEAM = "wrong_team"

    # 401
    INVALID_CREDENTIALS = "invalid_credentials"
    INVALID_REFRESH_TOKEN = "invalid_refresh_token"
    INVALID_SERVICE_TOKEN = "invalid_service_token"

    # 403
    FORBIDDEN = "forbidden"
    NOT_A_TEAM_MEMBER = "not_a_team_member"
    NOT_A_MEMBER = "not_a_member"
    CANNOT_JOIN_PRIVATE = "cannot_join_private"
    CANNOT_READ_CHANNEL = "cannot_read_channel"
    NOT_FILE_OWNER = "not_file_owner"

    # 404
    TEAM_NOT_FOUND = "team_not_found"
    CHANNEL_NOT_FOUND = "channel_not_found"
    MEMBER_NOT_FOUND = "member_not_found"
    INVITE_NOT_FOUND = "invite_not_found"
    FILE_NOT_FOUND = "file_not_found"
    SUBSCRIPTION_NOT_FOUND = "subscription_not_found"
    USER_NOT_FOUND = "user_not_found"

    # 409
    EMAIL_TAKEN = "email_taken"
    TEAM_LIMIT_REACHED = "team_limit_reached"
    LAST_OWNER = "last_owner"
    INVITE_LIMIT_REACHED = "invite_limit_reached"
    CHANNEL_NAME_TAKEN = "channel_name_taken"
    CHANNEL_ARCHIVED = "channel_archived"
    USE_LEAVE = "use_leave"
    FILE_ATTACHED = "file_attached"
    FILE_NOT_READY = "file_not_ready"
    FILE_ALREADY_ATTACHED = "file_already_attached"

    # 410
    UPLOAD_EXPIRED = "upload_expired"
    INVITE_INVALID = "invite_invalid"

    # 429
    TOO_MANY_ATTEMPTS = "too_many_attempts"
