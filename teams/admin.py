from django.contrib import admin

from teams.models import Invite, Team, TeamMember


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "created_by", "created_at", "deleted_at"]
    list_filter = ["deleted_at"]
    search_fields = ["name"]
    readonly_fields = ["id", "created_at", "deleted_at"]

    def has_delete_permission(self, request, obj=None):
        return False  # teams are soft-deleted by TeamService.delete; a hard delete cascades


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ["user", "team", "role", "joined_at"]
    list_filter = ["role"]
    search_fields = ["user__email", "team__name"]
    readonly_fields = ["id", "joined_at"]

    # view only: role and membership changes go through TeamService (last-owner rule)
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ["code", "team", "created_by", "uses", "max_uses", "expires_at", "revoked_at"]
    list_filter = ["revoked_at"]
    search_fields = ["code", "team__name"]
    readonly_fields = ["id", "created_at"]

    def has_delete_permission(self, request, obj=None):
        return False  # invites are revoked (revoked_at), never deleted
