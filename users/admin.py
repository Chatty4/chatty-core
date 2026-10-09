from asgiref.sync import async_to_sync
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from users.models import User
from users.services import UserService


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "display_name", "is_active", "is_staff", "date_joined"]
    list_filter = ["is_active", "is_staff"]
    search_fields = ["email", "display_name"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("display_name", "avatar_id", "timezone")}),
        ("Permissions", {"fields": ("is_active", "is_staff")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "display_name", "password1", "password2"),
            },
        ),
    )
    filter_horizontal = ()

    # deactivation only through the action below, so the future
    # user.deactivated event is never skipped

    readonly_fields = ["is_active"]
    actions = ["deactivate"]

    @admin.action(description="Deactivate selected users")
    def deactivate(self, request, queryset):
        user_ids = list(queryset.values_list("id", flat=True))
        deactivated = async_to_sync(UserService.deactivate)(user_ids)
        self.message_user(request, f"Deactivated {len(deactivated)} user(s).", messages.SUCCESS)
