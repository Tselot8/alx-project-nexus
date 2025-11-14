from django.contrib import admin
from .models import Category, Poll, Option, Vote, Comment, AuditLog

admin.site.register(Category)
admin.site.register(Poll)
admin.site.register(Option)
admin.site.register(Vote)
admin.site.register(Comment)
admin.site.register(AuditLog)
