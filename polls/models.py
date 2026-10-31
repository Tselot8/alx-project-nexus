import uuid
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
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

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        CLOSED = "closed", "Closed"
        ARCHIVED = "archived", "Archived"

    class ResultsVisibility(models.TextChoices):
        IMMEDIATE = "immediate", "Immediately"
        AFTER_VOTING = "after_voting", "After voting"
        AFTER_CLOSING = "after_closing", "After closing"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.TextField(null=False)
    description = models.TextField(null=True, blank=True)
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='polls',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='polls',
    )
    is_public = models.BooleanField(default=True)
    allow_multiple = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    # Dormant C metadata: legacy creation remains published and immediate.
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default="published",
        db_default="published",
        editable=False,
    )
    results_visibility = models.CharField(
        max_length=16,
        choices=ResultsVisibility.choices,
        default="immediate",
        db_default="immediate",
        editable=False,
    )
    min_selections = models.IntegerField(
        default=1,
        db_default=1,
        editable=False,
    )
    max_selections = models.IntegerField(
        null=True,
        blank=True,
        default=None,
        editable=False,
    )
    version = models.BigIntegerField(
        default=1,
        db_default=1,
        editable=False,
    )
    configuration_locked = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        editable=False,
        help_text=(
            "NULL means unknown legacy history. Only explicit False "
            "means verified never voted; True is a permanent lock."
        ),
    )

    class Meta:
        indexes = [
            models.Index(fields=['created_by'], name='idx_polls_created_by'),
            models.Index(fields=['category'], name='idx_polls_category_id'),
            models.Index(fields=['expires_at'], name='idx_polls_expires_at'),
            models.Index(fields=['is_public'], name='idx_polls_is_public'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "draft",
                        "published",
                        "closed",
                        "archived",
                    ]
                ),
                name="ck_poll_status",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    results_visibility__in=[
                        "immediate",
                        "after_voting",
                        "after_closing",
                    ]
                ),
                name="ck_poll_results_vis",
            ),
            models.CheckConstraint(
                condition=models.Q(min_selections__gte=1),
                name="ck_poll_min_sel",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(max_selections__isnull=True)
                    | models.Q(max_selections__gte=models.F("min_selections"))
                ),
                name="ck_poll_max_sel",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(allow_multiple=True)
                    | (
                        models.Q(min_selections=1)
                        & (
                            models.Q(max_selections__isnull=True)
                            | models.Q(max_selections=1)
                        )
                    )
                ),
                name="ck_poll_single_limits",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="ck_poll_version",
            ),
        ]

    def clean(self):
        """Validate metadata only; C does not activate lifecycle services."""
        super().clean()
        errors = {}
        if self.status not in self.Status.values:
            errors["status"] = "Select a valid poll status."
        if self.results_visibility not in self.ResultsVisibility.values:
            errors["results_visibility"] = "Select a valid results policy."
        if not isinstance(self.min_selections, int) or self.min_selections < 1:
            errors["min_selections"] = "Minimum selections must be at least 1."
        if self.max_selections is not None and (
            not isinstance(self.max_selections, int)
            or not isinstance(self.min_selections, int)
            or self.max_selections < self.min_selections
        ):
            errors["max_selections"] = "Maximum must be at least the minimum."
        if not self.allow_multiple and (
            self.min_selections != 1 or self.max_selections not in (None, 1)
        ):
            errors["allow_multiple"] = "Single-choice limits must be 1."
        if not isinstance(self.version, int) or self.version < 1:
            errors["version"] = "Version must be at least 1."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.question[:80]


# Option
class Option(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(
        Poll, on_delete=models.CASCADE, related_name='options'
    )
    option_text = models.CharField(max_length=255, null=False)
    votes_count = models.IntegerField(default=0)  # cached total

    class Meta:
        indexes = [models.Index(fields=['poll'], name='idx_options_poll_id')]
        constraints = [
            models.UniqueConstraint(
                fields=["id", "poll"],
                name="uq_option_id_poll",
            ),
        ]

    def __str__(self):
        return self.option_text


# Vote
class Vote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='votes',
    )
    poll = models.ForeignKey(
        Poll, on_delete=models.CASCADE, related_name='votes'
    )
    option = models.ForeignKey(
        Option, on_delete=models.CASCADE, related_name='votes'
    )
    voted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=['poll'], name='idx_votes_poll_id'),
            models.Index(fields=['user'], name='idx_votes_user_id'),
            models.Index(
                fields=['poll', 'option'], name='idx_votes_poll_option'
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'option'], name='unique_user_poll_vote'
            )
        ]

    def __str__(self):
        return f'{self.user} -> {self.option}'


# Comment
class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(
        Poll, on_delete=models.CASCADE, related_name='comments'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='comments',
    )
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
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='audit_logs',
    )
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


class Ballot(models.Model):
    """Dormant storage; save() does not run clean() automatically."""

    class Source(models.TextChoices):
        NATIVE = "native", "Native"
        LEGACY = "legacy", "Legacy"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    poll = models.ForeignKey(
        Poll,
        on_delete=models.PROTECT,
        related_name="ballots",
        db_index=False,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ballots",
    )
    submitted_at = models.DateTimeField(null=True, blank=True, default=None)
    source = models.CharField(
        max_length=6,
        choices=Source.choices,
        default="native",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["poll", "user"],
                name="uq_ballot_poll_user",
            ),
            models.UniqueConstraint(
                fields=["id", "poll"],
                name="uq_ballot_id_poll",
            ),
            models.CheckConstraint(
                condition=models.Q(source__in=["native", "legacy"]),
                name="ck_ballot_source",
            ),
        ]

    def clean(self):
        """Validate persisted selections without implementing submission."""
        super().clean()
        errors = {}
        if self.source not in self.Source.values:
            errors["source"] = "Select a valid ballot source."
        if self.submitted_at is not None:
            if self._state.adding:
                errors["submitted_at"] = (
                    "Save an incomplete ballot before validating submission."
                )
            else:
                count = self.selections.count()
                poll = (
                    Poll.objects.using(self._state.db)
                    .filter(pk=self.poll_id)
                    .first()
                )
                if count == 0:
                    errors["submitted_at"] = (
                        "A submitted ballot must contain a selection."
                    )
                elif poll is not None:
                    minimum = poll.min_selections if poll.allow_multiple else 1
                    maximum = poll.max_selections if poll.allow_multiple else 1
                    if maximum is None:
                        maximum = poll.options.count()
                    if count < minimum or count > maximum:
                        errors["submitted_at"] = (
                            "Selection count is outside the poll limits."
                        )
        if errors:
            raise ValidationError(errors)


class BallotSelection(models.Model):
    """Same-poll membership also has PostgreSQL composite foreign keys."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ballot = models.ForeignKey(
        Ballot,
        on_delete=models.CASCADE,
        related_name="selections",
        db_index=False,
    )
    poll = models.ForeignKey(
        Poll,
        on_delete=models.PROTECT,
        related_name="ballot_selections",
        db_index=False,
    )
    option = models.ForeignKey(
        Option,
        on_delete=models.PROTECT,
        related_name="ballot_selections",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ballot", "option"],
                name="uq_selection_ballot_option",
            ),
        ]
        indexes = [
            models.Index(
                fields=["poll", "option"],
                name="idx_selection_poll_option",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        ballot_poll = (
            Ballot.objects.using(self._state.db)
            .filter(pk=self.ballot_id)
            .values_list("poll_id", flat=True)
            .first()
        )
        option_poll = (
            Option.objects.using(self._state.db)
            .filter(pk=self.option_id)
            .values_list("poll_id", flat=True)
            .first()
        )
        if ballot_poll is not None and self.poll_id != ballot_poll:
            errors["poll"] = "Selection poll must match the ballot poll."
        if option_poll is not None and self.poll_id != option_poll:
            errors["option"] = "Selected option must belong to the poll."
        if errors:
            raise ValidationError(errors)


class PollShareToken(models.Model):
    """Digest storage only; C never issues or generates share tokens."""

    poll = models.OneToOneField(
        Poll,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="share_token",
    )
    token_digest = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        default=None,
        editable=False,
        validators=[
            RegexValidator(
                regex=r"\A[0-9a-f]{64}\Z",
                message=(
                    "Digest must contain 64 lowercase hexadecimal characters."
                ),
            )
        ],
    )
    generation = models.PositiveBigIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["token_digest"],
                name="uq_share_digest",
            ),
            models.CheckConstraint(
                condition=models.Q(generation__gte=1),
                name="ck_share_generation",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(token_digest__isnull=True)
                    | models.Q(token_digest__regex=r"^[0-9a-f]{64}$")
                ),
                name="ck_share_digest",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.token_digest is not None:
            try:
                self._meta.get_field("token_digest").validators[0](
                    self.token_digest
                )
            except ValidationError:
                errors["token_digest"] = (
                    "Digest must contain 64 lowercase hexadecimal characters."
                )
        if not isinstance(self.generation, int) or self.generation < 1:
            errors["generation"] = "Generation must be at least 1."
        if errors:
            raise ValidationError(errors)
