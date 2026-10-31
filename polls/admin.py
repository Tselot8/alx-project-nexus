from django.contrib import admin
from .models import Poll, Option, Vote, Category, Comment, AuditLog


class OptionInline(admin.TabularInline):
    model = Option
    extra = 2  # number of empty option fields shown by default


class PollAdmin(admin.ModelAdmin):
    inlines = [OptionInline]
    list_display = (
        'question',
        'created_by',
        'category',
        'is_public',
        'created_at',
    )
    search_fields = ('question',)
    list_filter = ('is_public', 'category')


admin.site.register(Poll, PollAdmin)
admin.site.register(Option)


class HistoricalVoteAdmin(admin.ModelAdmin):
    """Immutable source evidence: all participation now uses ballots."""

    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Vote, HistoricalVoteAdmin)
admin.site.register(Category)
admin.site.register(Comment)
admin.site.register(AuditLog)
