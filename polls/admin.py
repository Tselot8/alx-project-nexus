from django.contrib import admin
from .models import Poll, Option, Vote, Category, Comment, AuditLog

class OptionInline(admin.TabularInline):
    model = Option
    extra = 2   # number of empty option fields shown by default

class PollAdmin(admin.ModelAdmin):
    inlines = [OptionInline]
    list_display = ('question', 'created_by', 'category', 'is_public', 'created_at')
    search_fields = ('question',)
    list_filter = ('is_public', 'category')

admin.site.register(Poll, PollAdmin)
admin.site.register(Option)
admin.site.register(Vote)
admin.site.register(Category)
admin.site.register(Comment)
admin.site.register(AuditLog)
