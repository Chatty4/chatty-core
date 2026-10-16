import secrets
from uuid import UUID

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from channels.models import Channel, ChannelMember
from channels.repositories import ChannelMemberRepository, ChannelRepository
from shared.codes import ErrorCode
from shared.exceptions import Conflict, Gone, NotFound, PermissionDenied, RateLimited
from shared.redis import rate_limit
from teams.models import Invite, Team, TeamMember
from teams.repositories import InviteRepository, TeamMemberRepository, TeamRepository
from teams.schemas import (
    BaseInviteResult,
    CreateTeamResult,
    InviteLookupResult,
    InviteResult,
    JoinTeamResult,
    TeamDetailResult,
    TeamPreview,
    TeamResult,
)

LOOKUP_LIMIT = 30
LOOKUP_WINDOW = 60
MANAGERS = {TeamMember.Role.OWNER, TeamMember.Role.ADMIN}


class TeamService:
    @staticmethod
    async def _get_team_or_404(team_id: UUID) -> Team:
        team = await TeamRepository.get_by_id(team_id)
        if team is None:
            raise NotFound(ErrorCode.TEAM_NOT_FOUND)
        return team

    @staticmethod
    async def _get_member_or_403(team_id: UUID, user_id: UUID) -> TeamMember:
        member = await TeamMemberRepository.get_member(team_id, user_id)
        if member is None:
            raise PermissionDenied(ErrorCode.NOT_A_TEAM_MEMBER)
        return member

    @staticmethod
    async def create(name: str, user_id: UUID) -> CreateTeamResult:
        if await TeamRepository.count_created_by(user_id) >= 10:
            raise Conflict(ErrorCode.TEAM_LIMIT_REACHED)
        return await sync_to_async(TeamService._create_sync)(name, user_id)

    @staticmethod
    @transaction.atomic
    def _create_sync(name: str, user_id: UUID) -> CreateTeamResult:
        team = TeamRepository.create_sync(name, created_by_id=user_id)
        TeamMemberRepository.create_sync(team=team, user_id=user_id, role=TeamMember.Role.OWNER)
        channel = ChannelRepository.create_sync(
            team=team,
            name="general",
            kind=Channel.Kind.PUBLIC,
            is_default=True,
            created_by_id=user_id,
        )
        ChannelMemberRepository.create_sync(
            channel=channel,
            user_id=user_id,
            role=ChannelMember.Role.OWNER,
            notify_level=ChannelMember.NotifyLevel.MENTIONS,
        )
        return CreateTeamResult(
            id=team.id,
            name=team.name,
            icon_file_id=team.icon_id,
            role=TeamMember.Role.OWNER,
            member_count=1,
            general_channel_id=channel.id,
            created_at=team.created_at,
        )

    @staticmethod
    async def list_for_user(user_id: UUID) -> list[TeamResult]:
        teams = await TeamRepository.list_by_user(user_id)
        return [
            TeamResult(
                id=team.id,
                name=team.name,
                icon_file_id=team.icon_id,
                role=team.role,  # type: ignore[attr-defined]
                member_count=team.member_count,  # type: ignore[attr-defined]
                created_at=team.created_at,
            )
            for team in teams
        ]

    @staticmethod
    async def get(team_id: UUID, user_id: UUID) -> TeamDetailResult:
        team, member = await TeamService.require_member(team_id, user_id)
        count = await TeamMemberRepository.count_members(team_id)
        return TeamDetailResult(
            id=team.id,
            name=team.name,
            icon_file_id=team.icon_id,
            my_role=member.role,
            member_count=count,
            created_by=team.created_by_id,  # type: ignore[attr-defined]
            created_at=team.created_at,
        )

    @staticmethod
    async def update(
        team_id: UUID, user_id: UUID, name: str, icon_file_id: UUID | None
    ) -> TeamDetailResult:
        """
        TODO: validate icon_file_id against the files model (ready,
        team_icon purpose, same team).
        """
        team, member = await TeamService.require_member(
            team_id, user_id, roles={TeamMember.Role.OWNER, TeamMember.Role.ADMIN}
        )
        team = await TeamRepository.update(team, name=name, icon_id=icon_file_id)
        count = await TeamMemberRepository.count_members(team_id)
        return TeamDetailResult(
            id=team.id,
            name=team.name,
            icon_file_id=team.icon_id,
            my_role=member.role,
            member_count=count,
            created_by=team.created_by_id,  # type: ignore[attr-defined]
            created_at=team.created_at,
        )

    @staticmethod
    async def delete(team_id: UUID, user_id: UUID) -> None:
        """TODO: publish team.deleted event after commit."""
        team, _ = await TeamService.require_member(team_id, user_id, roles={TeamMember.Role.OWNER})
        await TeamRepository.delete(team)

    @staticmethod
    async def require_member(
        team_id: UUID, user_id: UUID, roles: set[TeamMember.Role] | None = None
    ) -> tuple[Team, TeamMember]:
        """The user's membership in a live team. Every /teams/{team_id}/... endpoint starts here.

        Raises team_not_found, not_a_team_member, or forbidden when `roles` is given and the
        user's role isn't in it.
        """
        team = await TeamService._get_team_or_404(team_id)
        member = await TeamService._get_member_or_403(team_id, user_id)
        if roles is not None and member.role not in roles:
            raise PermissionDenied()

        return team, member

    @staticmethod
    async def list_members(
        team_id: UUID,
        user_id: UUID,
        limit: int,
        cursor: str | None = None,
        q: str | None = None,
        user_ids: list[UUID] | None = None,
    ) -> tuple[list[TeamMember], str | None]:
        await TeamService.require_member(team_id, user_id)
        if user_ids is not None:  # lookup mode: exactly these members, never paginated
            return await TeamMemberRepository.list_members_by_user_ids(team_id, user_ids), None
        return await TeamMemberRepository.list_members(team_id, q, cursor, limit)

    @staticmethod
    async def change_role(team_id: UUID, user_id: UUID, target_id: UUID, role: str) -> TeamMember:
        _, me = await TeamService.require_member(team_id, user_id, roles=MANAGERS)
        return await sync_to_async(TeamService._change_role_sync)(team_id, me.role, target_id, role)

    @staticmethod
    @transaction.atomic
    def _change_role_sync(team_id: UUID, my_role: str, target_id: UUID, role: str) -> TeamMember:
        # Locking the owners first makes two concurent demotions run one after the other,
        # so they cna't both pas the last-owner check.
        owner_ids = TeamMemberRepository.lock_owner_ids_sync(team_id)
        target = TeamMemberRepository.get_member_sync(team_id, target_id)
        if target is None:
            raise NotFound(ErrorCode.MEMBER_NOT_FOUND)

        owner = TeamMember.Role.OWNER
        if my_role != owner and owner in (role, target.role):
            raise PermissionDenied()  # only an owner can make or change an owner
        if target.role == owner and role != owner and len(owner_ids) == 1:
            raise Conflict(ErrorCode.LAST_OWNER)

        TeamMemberRepository.update_role_sync(target, role)
        # TODO(CHAT-172): publish team.member.changed (role_changed) after commit

        return target

    @staticmethod
    async def remove_member(team_id: UUID, user_id: UUID, target_id: UUID) -> None:
        _, me = await TeamService.require_member(team_id, user_id, roles=MANAGERS)
        if target_id == user_id:
            raise Conflict(ErrorCode.USE_LEAVE)
        target = await TeamMemberRepository.get_member(team_id, target_id)
        if target is None:
            raise NotFound(ErrorCode.MEMBER_NOT_FOUND)
        if me.role != TeamMember.Role.OWNER and target.role == TeamMember.Role.OWNER:
            raise PermissionDenied()  # admins can't remove owners
        await sync_to_async(TeamService._remove_member_sync)(team_id, target_id)

    @staticmethod
    @transaction.atomic
    def _remove_member_sync(team_id: UUID, user_id: UUID) -> None:
        """Take the user out of a team and all its channes."""
        ChannelMemberRepository.delete_in_team_sync(team_id, user_id)
        TeamMemberRepository.delete_sync(team_id, user_id)
        # TODO(CHAT-172): publish team.member.changed (removed) after commit.

    @staticmethod
    async def leave(team_id: UUID, user_id: UUID) -> None:
        """TODO: publish team.member.changed (left) after commit."""
        await TeamService.require_member(team_id, user_id)
        await sync_to_async(TeamService._leave_sync)(team_id, user_id)

    @staticmethod
    @transaction.atomic
    def _leave_sync(team_id: UUID, user_id: UUID) -> None:
        """Guard last-owner then reuse _remove_member_sync. Lock ensures two concurrent leaves
        can't both pass the last-owner check."""
        owner_ids = TeamMemberRepository.lock_owner_ids_sync(team_id)
        if user_id in owner_ids and len(owner_ids) == 1:
            raise Conflict(ErrorCode.LAST_OWNER)
        TeamService._remove_member_sync(team_id, user_id)


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
    async def lookup(code: str, ip: str) -> InviteLookupResult:
        """Public invite preview. Rate limited 30/min per IP"""
        retry_after = await rate_limit(f"invite_lookup:{ip}", LOOKUP_LIMIT, LOOKUP_WINDOW)
        if retry_after:
            raise RateLimited(retry_after)

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
    async def join(code: str, user_id: UUID) -> JoinTeamResult:
        """Join the team with an invite. Already a member: nothing changes and uses don't go up."""
        invite = await InviteService._get_invite_or_404(code)
        return await sync_to_async(InviteService._join_sync)(invite.id, invite.team, user_id)

    @staticmethod
    @transaction.atomic
    def _join_sync(invite_id: UUID, team: Team, user_id: UUID) -> JoinTeamResult:
        """
        Lock the team so concurrent joins (same or different invite) run one at a time,
        then add the user to the team and its default channels.
        """
        TeamRepository.lock_sync(team.id)
        invite = InviteRepository.lock_by_id_sync(invite_id)

        member = TeamMemberRepository.get_member_sync(team.id, user_id)
        if member is not None:
            return InviteService._already_member(team, member)

        valid, reason = InviteService._check_validity(invite)
        if not valid:
            raise Gone(ErrorCode.INVITE_INVALID, reason)

        TeamMemberRepository.create_sync(team=team, user_id=user_id, role=TeamMember.Role.MEMBER)
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
