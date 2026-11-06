from django.contrib import admin
from .models import Poll, Option, Vote, Category, Comment, AuditLog


class ReadOnlyRecordAdmin(admin.ModelAdmin):
    """No admin mutation bypass around transactional API/domain safeguards."""

    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PollAdmin(ReadOnlyRecordAdmin):
    list_display = (
        "question",
        "created_by",
        "category",
        "is_public",
        "created_at",
    )
    search_fields = ("question",)
    list_filter = ("is_public", "category")


admin.site.register(Poll, PollAdmin)
admin.site.register(Option, ReadOnlyRecordAdmin)


class HistoricalVoteAdmin(ReadOnlyRecordAdmin):
    """Immutable source evidence: all participation now uses ballots."""


admin.site.register(Vote, HistoricalVoteAdmin)
admin.site.register(Category)
admin.site.register(Comment)
admin.site.register(AuditLog, ReadOnlyRecordAdmin)
