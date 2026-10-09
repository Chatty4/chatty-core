from django.contrib import admin

from authn.models import RefreshToken


@admin.register(RefreshToken)
class RefreshTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "created_at", "expires_at", "revoked_at")
    list_filter = ("revoked_at",)
    search_fields = ("user__email",)
    readonly_fields = ("id", "token_hash", "created_at")
    ordering = ("-created_at",)
