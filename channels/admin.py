from django.contrib import admin

from channels.models import Channel, ChannelMember


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ["name", "team", "kind", "is_default", "created_at", "archived_at"]
    list_filter = ["kind", "is_default", "archived_at"]
    search_fields = ["name", "team__name"]
    readonly_fields = ["id", "created_at"]


@admin.register(ChannelMember)
class ChannelMemberAdmin(admin.ModelAdmin):
    list_display = ["user", "channel", "role", "notify_level", "muted", "hidden", "joined_at"]
    list_filter = ["role", "notify_level", "muted", "hidden"]
    search_fields = ["user__email", "channel__name"]
    readonly_fields = ["id", "joined_at"]
