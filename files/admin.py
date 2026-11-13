from django.contrib import admin

from files.models import File


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ["filename", "purpose", "status", "owner", "team", "size", "created_at"]
    list_filter = ["purpose", "status"]
    search_fields = ["filename", "owner__email", "team__name"]
    readonly_fields = ["id", "created_at"]
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
