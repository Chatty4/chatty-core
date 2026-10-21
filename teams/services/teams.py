from dataclasses import asdict
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import transaction

from channels.models import Channel, ChannelMember
from channels.repositories import ChannelMemberRepository, ChannelRepository
from channels.schemas import MembershipAction, MembershipChanged
from shared import events
from shared.codes import ErrorCode
from shared.events import EventType
from shared.exceptions import Conflict, NotFound, PermissionDenied
from teams.models import Team, TeamMember
from teams.repositories import InviteRepository, TeamMemberRepository, TeamRepository
from teams.schemas import (
    CreateTeamResult,
    TeamDeleted,
    TeamDetailResult,
    TeamMemberAction,
    TeamMemberChanged,
    TeamResult,
)

MANAGERS = {TeamMember.Role.OWNER, TeamMember.Role.ADMIN}


class TeamService:
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
    def _get_manager_sync(team_id: UUID, user_id: UUID) -> TeamMember:
        """My membership read inside the transaction, or the same errors as require_member."""
        me = TeamMemberRepository.get_member_sync(team_id, user_id)
        if me is None:
            raise PermissionDenied(ErrorCode.NOT_A_TEAM_MEMBER)
        if me.role not in MANAGERS:
            raise PermissionDenied()
        return me

    @staticmethod
    async def create(name: str, user_id: UUID) -> CreateTeamResult:
        return await sync_to_async(TeamService._create_sync)(name, user_id)

    @staticmethod
    @transaction.atomic
    def _create_sync(name: str, user_id: UUID) -> CreateTeamResult:
        if TeamRepository.count_created_by_sync(user_id) >= 10:
            raise Conflict(ErrorCode.TEAM_LIMIT_REACHED)
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
    async def get(team_id: UUID, user_id: UUID) -> TeamDetailResult:
        team, member = await TeamService.require_member(team_id, user_id)
        return await TeamService._detail(team, member)

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
        return await TeamService._detail(team, member)

    @staticmethod
    async def _detail(team: Team, member: TeamMember) -> TeamDetailResult:
        """The team as GET /teams/{team_id} returns it, from rows already loaded."""
        count = await TeamMemberRepository.count_members(team.id)
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
        """Soft delete the team. Owners only."""
        team, _ = await TeamService.require_member(team_id, user_id, roles={TeamMember.Role.OWNER})
        await TeamRepository.delete(team)
        await events.publish(EventType.TEAM_DELETED, asdict(TeamDeleted(team.id)))

    @staticmethod
    async def change_role(team_id: UUID, user_id: UUID, target_id: UUID, role: str) -> TeamMember:
        await TeamService.require_member(team_id, user_id, roles=MANAGERS)
        target = await sync_to_async(TeamService._change_role_sync)(
            team_id, user_id, target_id, role
        )
        await events.publish(
            EventType.TEAM_MEMBER_CHANGED,
            asdict(
                TeamMemberChanged(target_id, team_id, TeamMemberAction.ROLE_CHANGED, target.role)
            ),
        )
        return target

    @staticmethod
    @transaction.atomic
    def _change_role_sync(team_id: UUID, user_id: UUID, target_id: UUID, role: str) -> TeamMember:
        """Roles are re-read under the team lock, so a change made a moment earlier counts."""
        owner_ids = TeamMemberRepository.lock_owner_ids_sync(team_id)
        me = TeamService._get_manager_sync(team_id, user_id)
        target = TeamMemberRepository.get_member_sync(team_id, target_id)
        if target is None:
            raise NotFound(ErrorCode.MEMBER_NOT_FOUND)

        owner = TeamMember.Role.OWNER
        if me.role != owner and owner in (role, target.role):
            raise PermissionDenied()  # only an owner can make or change an owner
        if target.role == owner and role != owner and owner_ids == [target_id]:
            raise Conflict(ErrorCode.LAST_OWNER)

        TeamMemberRepository.update_role_sync(target, role)

        return target

    @staticmethod
    async def remove_member(team_id: UUID, user_id: UUID, target_id: UUID) -> None:
        await TeamService.require_member(team_id, user_id, roles=MANAGERS)
        if target_id == user_id:
            raise Conflict(ErrorCode.USE_LEAVE)
        changes = await sync_to_async(TeamService._remove_sync)(team_id, user_id, target_id)
        await events.publish(
            EventType.TEAM_MEMBER_CHANGED,
            asdict(TeamMemberChanged(target_id, team_id, TeamMemberAction.REMOVED, None)),
        )
        for change in changes:
            await events.publish(EventType.MEMBERSHIP_CHANGED, asdict(change))

    @staticmethod
    @transaction.atomic
    def _remove_sync(team_id: UUID, user_id: UUID, target_id: UUID) -> list[MembershipChanged]:
        """Roles are re-read under the team lock: an owner removed a moment earlier can't remove
        anyone, and an admin can't remove a member who was just promoted to owner."""
        TeamMemberRepository.lock_owner_ids_sync(team_id)
        me = TeamService._get_manager_sync(team_id, user_id)
        target = TeamMemberRepository.get_member_sync(team_id, target_id)
        if target is None:
            raise NotFound(ErrorCode.MEMBER_NOT_FOUND)
        if me.role != TeamMember.Role.OWNER and target.role == TeamMember.Role.OWNER:
            raise PermissionDenied()  # admins can't remove owners
        return TeamService._remove_member_sync(team_id, target_id)

    @staticmethod
    @transaction.atomic
    def _remove_member_sync(team_id: UUID, user_id: UUID) -> list[MembershipChanged]:
        """Take the user out of a team and all its channels, and revoke the invites they created
        (their links shouldn't keep letting people into a team they left). In a private channel
        where they were the only owner, the member who joined first becomes owner, as with
        channel leave. Returns the hand-off events to publish once the transaction has
        committed."""
        changes = []
        for channel_id in ChannelMemberRepository.list_private_channel_ids_sync(team_id, user_id):
            owner_ids = ChannelMemberRepository.lock_owner_ids_sync(channel_id)
            ChannelMemberRepository.delete_sync(channel_id, user_id)
            if set(owner_ids) <= {user_id}:  # no active owner other than them is left
                promoted = ChannelMemberRepository.promote_first_joined_sync(channel_id)
                if promoted is not None:
                    changes.append(
                        MembershipChanged(promoted, channel_id, team_id, MembershipAction.SETTINGS)
                    )
        ChannelMemberRepository.delete_in_team_sync(team_id, user_id)
        TeamMemberRepository.delete_sync(team_id, user_id)
        InviteRepository.revoke_created_by_sync(team_id, user_id)
        return changes

    @staticmethod
    async def leave(team_id: UUID, user_id: UUID) -> None:
        """Leave the team and all its channels. The last owner can't leave."""
        await TeamService.require_member(team_id, user_id)
        changes = await sync_to_async(TeamService._leave_sync)(team_id, user_id)
        await events.publish(
            EventType.TEAM_MEMBER_CHANGED,
            asdict(TeamMemberChanged(user_id, team_id, TeamMemberAction.LEFT, None)),
        )
        for change in changes:
            await events.publish(EventType.MEMBERSHIP_CHANGED, asdict(change))

    @staticmethod
    @transaction.atomic
    def _leave_sync(team_id: UUID, user_id: UUID) -> list[MembershipChanged]:
        """Guard last-owner then reuse _remove_member_sync. Lock ensures two concurrent leaves
        can't both pass the last-owner check."""
        owner_ids = TeamMemberRepository.lock_owner_ids_sync(team_id)
        if user_id in owner_ids and len(owner_ids) == 1:
            raise Conflict(ErrorCode.LAST_OWNER)
        return TeamService._remove_member_sync(team_id, user_id)

    @staticmethod
    async def hand_off_ownership(user_id: UUID) -> None:
        """Call after a user is deactivated, so none of their teams is left without an active
        owner."""
        changes = await sync_to_async(TeamService._hand_off_ownership_sync)(user_id)
        for change in changes:
            await events.publish(EventType.TEAM_MEMBER_CHANGED, asdict(change))

    @staticmethod
    @transaction.atomic
    def _hand_off_ownership_sync(user_id: UUID) -> list[TeamMemberChanged]:
        """In each team the user owns that has no active owner left, the admin who joined first
        becomes owner, or else the member who joined first. The user keeps their own role.
        Returns the events to publish once the transaction has committed."""
        changes = []
        for team_id in TeamMemberRepository.list_owned_team_ids_sync(user_id):
            TeamRepository.lock_sync(team_id)
            first = TeamMemberRepository.first_active_by_rank_sync(team_id)
            if first is not None and first.role != TeamMember.Role.OWNER:
                TeamMemberRepository.update_role_sync(first, TeamMember.Role.OWNER)
                changes.append(
                    TeamMemberChanged(
                        first.user_id,  # type: ignore[attr-defined]
                        team_id,
                        TeamMemberAction.ROLE_CHANGED,
                        TeamMember.Role.OWNER,
                    )
                )
        return changes
