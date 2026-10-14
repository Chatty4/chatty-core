from django.contrib import admin

from teams.models import Invite, Team, TeamMember


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "created_by", "created_at", "deleted_at"]
    list_filter = ["deleted_at"]
    search_fields = ["name"]
    readonly_fields = ["id", "created_at"]


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ["user", "team", "role", "joined_at"]
    list_filter = ["role"]
    search_fields = ["user__email", "team__name"]
    readonly_fields = ["id", "joined_at"]


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ["code", "team", "created_by", "uses", "max_uses", "expires_at", "revoked_at"]
    list_filter = ["revoked_at"]
    search_fields = ["code", "team__name"]
    readonly_fields = ["id", "created_at"]
