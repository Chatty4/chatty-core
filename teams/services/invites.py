import secrets
from uuid import UUID

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from channels.models import ChannelMember
from channels.repositories import ChannelMemberRepository, ChannelRepository
from shared.codes import ErrorCode
from shared.exceptions import Conflict, Gone, NotFound, PermissionDenied, RateLimited
from shared.redis import rate_limit
from teams.models import Invite, Team, TeamMember
from teams.repositories import InviteRepository, TeamMemberRepository, TeamRepository
from teams.schemas import (
    BaseInviteResult,
    InviteLookupResult,
    InviteResult,
    JoinTeamResult,
    TeamPreview,
)
from teams.services.teams import MANAGERS, TeamService

LOOKUP_LIMIT = 30
LOOKUP_WINDOW = 60


class InviteService:
    @staticmethod
    async def _get_invite_or_404(key: UUID | str) -> Invite:
        """Fetch an invite or raise invite_not_found. Pass a UUID to look up by id,
        a str to look up by code (also loads the team via select_related)."""
        if isinstance(key, UUID):
            invite = await InviteRepository.get_by_id(key)
        else:
            invite = await InviteRepository.get_by_code(key)
        if invite is None:
            raise NotFound(ErrorCode.INVITE_NOT_FOUND)
        return invite

    @staticmethod
    def _check_validity(invite: Invite) -> tuple[bool, str | None]:
        now = timezone.now()
        if invite.revoked_at is not None:
            return False, "revoked"
        if invite.expires_at is not None and invite.expires_at <= now:
            return False, "expired"
        if invite.max_uses != 0 and invite.uses >= invite.max_uses:
            return False, "used_up"
        return True, None

    @staticmethod
    async def _limit_code_guesses(ip: str) -> None:
        """Lookup and join share one budget, so neither can be used to guess codes."""
        retry_after = await rate_limit(f"invite_lookup:{ip}", LOOKUP_LIMIT, LOOKUP_WINDOW)
        if retry_after:
            raise RateLimited(retry_after)

    @staticmethod
    async def create(team_id: UUID, user_id: UUID, max_age: int, max_uses: int) -> InviteResult:
        await TeamService.require_member(team_id, user_id)
        return await sync_to_async(InviteService._create_sync)(team_id, user_id, max_age, max_uses)

    @staticmethod
    @transaction.atomic
    def _create_sync(team_id: UUID, user_id: UUID, max_age: int, max_uses: int) -> InviteResult:
        """Lock the team row, enforce the 100-invite cap, then insert."""
        if InviteRepository.count_active_sync(team_id) >= 100:
            raise Conflict(ErrorCode.INVITE_LIMIT_REACHED)

        code = InviteService._unique_code_sync()
        invite = InviteRepository.create_sync(team_id, user_id, code, max_age, max_uses)
        return InviteResult(
            id=invite.id,
            code=invite.code,
            url=f"{settings.APP_URL}/invite/{invite.code}",
            team_id=invite.team_id,  # type: ignore[attr-defined]
            created_by=invite.created_by_id,  # type: ignore[attr-defined]
            max_uses=invite.max_uses,
            uses=invite.uses,
            expires_at=invite.expires_at,
            created_at=invite.created_at,
        )

    @staticmethod
    def _unique_code_sync() -> str:
        """Generate an 8-char code that doesn't exist yet."""
        while True:
            code = secrets.token_urlsafe(6)
            if not InviteRepository.code_exists_sync(code):
                return code

    @staticmethod
    async def list_invites(team_id: UUID, user_id: UUID) -> list[BaseInviteResult]:
        """Active invites for the team. Owners and admins see all; members see only their own."""
        _, member = await TeamService.require_member(team_id, user_id)
        created_by_id = None if member.role in MANAGERS else user_id
        invites = await InviteRepository.list_active(team_id, created_by_id)

        return [
            BaseInviteResult(
                id=invite.id,
                code=invite.code,
                url=f"{settings.APP_URL}/invite/{invite.code}",
                created_by=invite.created_by_id,  # type: ignore[attr-defined]
                max_uses=invite.max_uses,
                uses=invite.uses,
                expires_at=invite.expires_at,
                created_at=invite.created_at,
            )
            for invite in invites
        ]

    @staticmethod
    async def lookup(code: str, ip: str) -> InviteLookupResult:
        """Public invite preview. Rate limited 30/min per IP"""
        await InviteService._limit_code_guesses(ip)

        invite = await InviteService._get_invite_or_404(code)

        valid, reason = InviteService._check_validity(invite)
        member_count = await TeamMemberRepository.count_members(invite.team.id)

        # TODO: presigned URL once file uploads are done
        return InviteLookupResult(
            code=code,
            valid=valid,
            reason=reason,
            team=TeamPreview(name=invite.team.name, icon_url=None, member_count=member_count),
            expires_at=invite.expires_at,
        )

    @staticmethod
    async def revoke(invite_id: UUID, user_id: UUID) -> None:
        """
        Revoke an invite. Creator, owner or admin only.
        Idempotent: already-revoked returns silently.
        """
        invite = await InviteService._get_invite_or_404(invite_id)
        _, member = await TeamService.require_member(invite.team_id, user_id)  # type: ignore[attr-defined]

        if invite.created_by_id != user_id and member.role not in MANAGERS:  # type: ignore[attr-defined]
            raise PermissionDenied()

        if invite.revoked_at is not None:
            return
        await InviteRepository.revoke(invite)

    @staticmethod
    async def revoke_all_created_by(user_id: UUID) -> None:
        """Call after a user is deactivated, so their links stop letting people in."""
        await InviteRepository.revoke_all_created_by(user_id)

    @staticmethod
    async def join(code: str, user_id: UUID, ip: str) -> JoinTeamResult:
        """Join the team with an invite. Already a member: nothing changes and uses don't go up."""
        await InviteService._limit_code_guesses(ip)
        invite = await InviteService._get_invite_or_404(code)
        return await sync_to_async(InviteService._join_sync)(invite.id, invite.team, user_id)

    @staticmethod
    @transaction.atomic
    def _join_sync(invite_id: UUID, team: Team, user_id: UUID) -> JoinTeamResult:
        """
        Lock the team so concurrent joins (same or different invite) run one at a time,
        then add the user to the team and its default channels.
        """
        if not TeamRepository.lock_sync(team.id):
            raise NotFound(ErrorCode.INVITE_NOT_FOUND)  # the team was deleted after the lookup
        invite = InviteRepository.lock_by_id_sync(invite_id)

        member = TeamMemberRepository.get_member_sync(team.id, user_id)
        if member is not None:
            return InviteService._already_member(team, member)

        valid, reason = InviteService._check_validity(invite)
        if not valid:
            raise Gone(ErrorCode.INVITE_INVALID, reason)

        TeamMemberRepository.create_sync(
            team=team, user_id=user_id, role=TeamMember.Role.MEMBER, invite=invite
        )
        # Rows left from an earlier membership (a channel add that raced with removal) must not
        # come back. DMs are safe: open_dm adds returning people again.
        ChannelMemberRepository.delete_in_team_sync(team.id, user_id)
        channel_ids = ChannelRepository.list_default_ids_sync(team.id)
        ChannelMemberRepository.bulk_create_sync(
            channel_ids,
            user_id,
            role=ChannelMember.Role.MEMBER,
            notify_level=ChannelMember.NotifyLevel.MENTIONS,
        )
        InviteRepository.increment_uses_sync(invite)

        # TODO(CHAT-172): on_commit publish team.member.changed (joined)
        # TODO(CHAT-172): on_commit publish membership.changed (added) per channel

        return JoinTeamResult(
            team_id=team.id,
            name=team.name,
            role=TeamMember.Role.MEMBER,
            already_member=False,
            channel_ids=channel_ids,
        )

    @staticmethod
    def _already_member(team: Team, member: TeamMember) -> JoinTeamResult:
        return JoinTeamResult(
            team_id=team.id,
            name=team.name,
            role=member.role,
            already_member=True,
            channel_ids=[],
        )
