import uuid
from django.db import models, transaction
from django.utils import timezone
from django.conf import settings

# Category
class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['name'], name='idx_categories_name')]

    def __str__(self):
        return self.name

# Poll
class Poll(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.TextField(null=False)
    description = models.TextField(null=True, blank=True)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name='polls')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='polls')
    is_public = models.BooleanField(default=True)
    allow_multiple = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['created_by'], name='idx_polls_created_by'),
            models.Index(fields=['category'], name='idx_polls_category_id'),
        ]

    def __str__(self):
        return self.question[:80]

# Option
class Option(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name='options')
    option_text = models.CharField(max_length=255, null=False)
    votes_count = models.IntegerField(default=0)  # cached total

    class Meta:
        indexes = [models.Index(fields=['poll'], name='idx_options_poll_id')]

    def __str__(self):
        return self.option_text

# Vote
class Vote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='votes')
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name='votes')
    option = models.ForeignKey(Option, on_delete=models.CASCADE, related_name='votes')
    voted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=['poll'], name='idx_votes_poll_id'),
            models.Index(fields=['user'], name='idx_votes_user_id'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'poll'],
                name='unique_user_poll_vote'
            )
        ]

    def __str__(self):
        return f'{self.user} -> {self.option}'

# Comment
class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comments')
    content = models.TextField(null=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['poll'], name='idx_comments_poll_id'),
            models.Index(fields=['user'], name='idx_comments_user_id'),
        ]

    def __str__(self):
        return f'Comment by {self.user} on {self.poll}'

# Audit log
class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='audit_logs')
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=50)
    target_id = models.UUIDField()
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=['user'], name='idx_audit_user_id'),
            models.Index(fields=['timestamp'], name='idx_audit_timestamp'),
        ]

    def __str__(self):
        return f'{self.action} by {self.user}'
