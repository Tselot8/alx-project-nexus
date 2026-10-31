"""Forward, upgrade, commit-time integrity, and reversal on test DBs only."""

from datetime import timedelta
import uuid

from django.db import connection, IntegrityError, ProgrammingError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from .test_schema_models import (
    catalog_constraints,
    catalog_index,
    COMPOSITE_FKS,
    POLL_CHECKS,
)

B1 = "0004_remove_vote_unique_user_poll_vote_and_more"
EXPAND = "0005_expand_poll_ballot_share_schema"
INDEX = "0006_option_pair_unique_index"
INTEGRITY = "0007_add_poll_and_selection_constraints"
LATEST = "0008_validate_schema_constraints"
OLD_MODELS = (
    ("accounts", "User"),
    ("accounts", "UserProfile"),
    ("polls", "Category"),
    ("polls", "Poll"),
    ("polls", "Option"),
    ("polls", "Vote"),
    ("polls", "Comment"),
    ("polls", "AuditLog"),
)


class SchemaMigrationTests(TransactionTestCase):
    """Never run schema transitions inside TestCase's enclosing transaction."""

    def setUp(self):
        super().setUp()
        self.assertEqual(connection.vendor, "postgresql")
        self.assertTrue(
            connection.settings_dict["NAME"].startswith("test_nexus_test_")
        )
        self.assertFalse(connection.in_atomic_block)
        executor = MigrationExecutor(connection)
        self.latest_targets = executor.loader.graph.leaf_nodes()
        self.assertEqual(
            executor.loader.graph.leaf_nodes("polls"), [("polls", LATEST)]
        )

    def tearDown(self):
        try:
            self.migrate(self.latest_targets)
        finally:
            super().tearDown()

    def migrate(self, target):
        targets = [("polls", target)] if isinstance(target, str) else target
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        state_targets = [node for node in targets if node[1] is not None]
        return executor.loader.project_state(state_targets).apps

    def seed_b1(self, apps):
        User = apps.get_model("accounts", "User")
        user = User.objects.create(
            email="history@example.invalid", username="history", password="!"
        )
        other = User.objects.create(
            email="other-history@example.invalid",
            username="other-history",
            password="!",
        )
        past = timezone.now() - timedelta(days=20)
        apps.get_model("accounts", "UserProfile").objects.create(
            user=user,
            bio="Historical profile",
            last_seen=past,
        )
        Category = apps.get_model("polls", "Category")
        category = Category.objects.create(name="Historical category")
        Poll = apps.get_model("polls", "Poll")
        public = Poll.objects.create(
            question="Historical public?",
            created_by=user,
            category=category,
            created_at=past,
        )
        private = Poll.objects.create(
            question="Historical private?",
            created_by=user,
            category=category,
            is_public=False,
            allow_multiple=True,
            created_at=past,
            expires_at=timezone.now() - timedelta(days=1),
        )
        Poll.objects.create(question="", created_by=user, created_at=past)
        Poll.objects.update(updated_at=past)
        Option = apps.get_model("polls", "Option")
        options = [
            Option.objects.create(
                poll=public, option_text="First", votes_count=-7
            ),
            Option.objects.create(
                poll=public, option_text="Second", votes_count=99
            ),
            Option.objects.create(
                poll=private, option_text="Private first", votes_count=0
            ),
            Option.objects.create(
                poll=private, option_text="Private second", votes_count=0
            ),
        ]
        Vote = apps.get_model("polls", "Vote")
        for poll, option, voter in (
            (public, options[0], user),
            (public, options[1], user),  # Historical single-choice anomaly.
            (private, options[2], user),
            (private, options[3], user),
            (public, options[2], other),  # Valid FKs, wrong logical poll.
        ):
            Vote.objects.create(
                user=voter,
                poll=poll,
                option=option,
                voted_at=past,
            )
        apps.get_model("polls", "Comment").objects.create(
            user=user,
            poll=public,
            content="Historical comment",
            created_at=past,
        )
        apps.get_model("polls", "AuditLog").objects.create(
            user=user,
            action="Voted on poll",
            target_type="Poll",
            target_id=public.pk,
            timestamp=past,
        )
        return (
            user.pk,
            public.pk,
            private.pk,
            [option.pk for option in options],
        )

    def take_snapshot(self, apps, field_names=None):
        names = field_names or {
            (app, name): [
                field.attname
                for field in apps.get_model(app, name)._meta.concrete_fields
            ]
            for app, name in OLD_MODELS
        }
        snapshot = {
            (app, name): list(
                apps.get_model(app, name)
                .objects.order_by("pk")
                .values(*names[(app, name)])
            )
            for app, name in OLD_MODELS
        }
        return snapshot, names

    def assert_empty_new_tables(self, apps):
        for name in ("Ballot", "BallotSelection", "PollShareToken"):
            self.assertEqual(apps.get_model("polls", name).objects.count(), 0)

    def assert_catalog_valid(self):
        for name in POLL_CHECKS:
            self.assertTrue(
                catalog_constraints("polls_poll")[name]["validated"]
            )
        for name in COMPOSITE_FKS:
            self.assertTrue(
                catalog_constraints("polls_ballotselection")[name]["validated"]
            )
        self.assertEqual(
            catalog_index("uq_option_id_poll")[:3], (True, True, True)
        )
        self.assertEqual(
            catalog_constraints("polls_option")["uq_option_id_poll"]["type"],
            "u",
        )

    def test_upgrade_from_b1_preserves_all_legacy_records_and_defaults(self):
        old = self.migrate(B1)
        self.seed_b1(old)
        before, names = self.take_snapshot(old)
        current = self.migrate(LATEST)
        after, _ = self.take_snapshot(current, names)
        self.assertEqual(after, before)
        for poll in current.get_model("polls", "Poll").objects.all():
            self.assertEqual(poll.status, "published")
            self.assertEqual(poll.results_visibility, "immediate")
            self.assertEqual(poll.min_selections, 1)
            self.assertIsNone(poll.max_selections)
            self.assertEqual(poll.version, 1)
            self.assertIsNone(poll.configuration_locked)
        self.assert_empty_new_tables(current)
        self.assert_catalog_valid()
        # Simulate an old binary's INSERT, which does not name new columns.
        users_before = before[("accounts", "User")]
        user_id = users_before[0]["id"]
        identifier = uuid.uuid4()
        now = timezone.now()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO polls_poll "
                "(id, question, description, category_id, created_by_id, "
                "is_public, allow_multiple, expires_at, "
                "created_at, updated_at) "
                "VALUES (%s, %s, NULL, NULL, %s, TRUE, FALSE, NULL, %s, %s)",
                [identifier, "Old writer?", user_id, now, now],
            )
        old_insert = current.get_model("polls", "Poll").objects.get(
            pk=identifier
        )
        self.assertEqual(
            (
                old_insert.status,
                old_insert.results_visibility,
                old_insert.min_selections,
                old_insert.version,
            ),
            ("published", "immediate", 1, 1),
        )
        self.assertIsNone(old_insert.max_selections)
        self.assertIsNone(old_insert.configuration_locked)

    def test_fresh_install_of_complete_graph_from_empty_application_schema(
        self,
    ):
        apps_to_reset = sorted({app for app, _ in self.latest_targets})
        self.migrate([(app, None) for app in apps_to_reset])
        tables = set(connection.introspection.table_names())
        self.assertEqual(tables, {"django_migrations"})
        current = self.migrate(self.latest_targets)
        tables = set(connection.introspection.table_names())
        self.assertTrue(
            {
                "accounts_user",
                "polls_poll",
                "polls_vote",
                "polls_ballot",
                "polls_ballotselection",
                "polls_pollsharetoken",
            }.issubset(tables)
        )
        self.assert_empty_new_tables(current)
        self.assertEqual(current.get_model("polls", "Vote").objects.count(), 0)
        self.assert_catalog_valid()

    def test_reversal_before_activation_preserves_b1_data_and_indexes(self):
        old = self.migrate(B1)
        self.seed_b1(old)
        before, names = self.take_snapshot(old)
        original_index = catalog_index("idx_option_poll_id")
        current = self.migrate(LATEST)
        self.assert_empty_new_tables(current)
        old = self.migrate(B1)
        self.assertEqual(self.take_snapshot(old, names)[0], before)
        self.assertIsNone(catalog_index("uq_option_id_poll"))
        self.assertEqual(catalog_index("idx_option_poll_id"), original_index)
        self.assertNotIn(
            "uq_option_id_poll", catalog_constraints("polls_option")
        )
        tables = set(connection.introspection.table_names())
        self.assertFalse(
            {
                "polls_ballot",
                "polls_ballotselection",
                "polls_pollsharetoken",
            }
            & tables
        )

    def test_not_valid_constraints_enforce_writes_before_later_validation(
        self,
    ):
        old = self.migrate(B1)
        user_id, poll_id, _, _ = self.seed_b1(old)
        current = self.migrate(INTEGRITY)
        executor = MigrationExecutor(connection)
        self.assertFalse(
            executor.loader.disk_migrations[("polls", INDEX)].atomic
        )
        self.assertFalse(
            executor.loader.disk_migrations[("polls", LATEST)].atomic
        )
        for name in POLL_CHECKS:
            self.assertFalse(
                catalog_constraints("polls_poll")[name]["validated"]
            )
        for name in COMPOSITE_FKS:
            self.assertFalse(
                catalog_constraints("polls_ballotselection")[name]["validated"]
            )
        Poll = current.get_model("polls", "Poll")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Poll.objects.filter(pk=poll_id).update(status="bad")
        self.assertIsNotNone(user_id)
        self.migrate(LATEST)
        self.assert_catalog_valid()

    def test_commit_rejects_invalid_bulk_and_raw_cross_poll_selections(self):
        apps = self.migrate(LATEST)
        User = apps.get_model("accounts", "User")
        user = User.objects.create(
            email="commit@example.invalid", username="commit", password="!"
        )
        Poll = apps.get_model("polls", "Poll")
        first = Poll.objects.create(question="First?", created_by=user)
        second = Poll.objects.create(question="Second?", created_by=user)
        Option = apps.get_model("polls", "Option")
        option = Option.objects.create(poll=second, option_text="Wrong poll")
        Ballot = apps.get_model("polls", "Ballot")
        ballot = Ballot.objects.create(poll=first, user=user)
        Selection = apps.get_model("polls", "BallotSelection")
        cases = [
            (kind, poll, constraint)
            for kind in ("bulk", "raw")
            for poll, constraint in (
                (first, "fk_selection_option_poll"),
                (second, "fk_selection_ballot_poll"),
            )
        ]
        for kind, selection_poll, constraint in cases:
            with self.subTest(write_kind=kind, constraint=constraint):
                with self.assertRaises(IntegrityError) as raised:
                    with transaction.atomic():
                        if kind == "bulk":
                            Selection.objects.bulk_create(
                                [
                                    Selection(
                                        ballot=ballot,
                                        poll=selection_poll,
                                        option=option,
                                    )
                                ]
                            )
                        else:
                            with connection.cursor() as cursor:
                                cursor.execute(
                                    "INSERT INTO polls_ballotselection "
                                    "(id, ballot_id, poll_id, option_id) "
                                    "VALUES (%s, %s, %s, %s)",
                                    [
                                        uuid.uuid4(),
                                        ballot.pk,
                                        selection_poll.pk,
                                        option.pk,
                                    ],
                                )
                        # Invalid row is visible here; COMMIT must reject it.
                        self.assertEqual(Selection.objects.count(), 1)
                self.assertEqual(
                    raised.exception.__cause__.diag.constraint_name,
                    constraint,
                )
                self.assertEqual(Selection.objects.count(), 0)

    def test_populated_schema_reversal_is_destructive_fixture_demonstration(
        self,
    ):
        old = self.migrate(B1)
        user_id, poll_id, _, option_ids = self.seed_b1(old)
        before, names = self.take_snapshot(old)
        apps = self.migrate(LATEST)
        ballot = apps.get_model("polls", "Ballot").objects.create(
            poll_id=poll_id,
            user_id=user_id,
            source="legacy",
        )
        apps.get_model("polls", "BallotSelection").objects.create(
            ballot_id=ballot.pk,
            poll_id=poll_id,
            option_id=option_ids[0],
        )
        apps.get_model("polls", "PollShareToken").objects.create(
            poll_id=poll_id,
            token_digest="a" * 64,
        )
        # Deliberately demonstrate fixture loss ONLY in the disposable test DB.
        old = self.migrate(B1)
        self.assertEqual(self.take_snapshot(old, names)[0], before)
        apps = self.migrate(LATEST)
        self.assert_empty_new_tables(apps)

    def test_reverse_to_index_stage_restores_index_and_allows_reapply(self):
        self.migrate(INDEX)
        self.assertEqual(
            catalog_index("uq_option_id_poll")[:3], (True, True, True)
        )
        self.assertNotIn(
            "uq_option_id_poll", catalog_constraints("polls_option")
        )
        self.migrate(LATEST)
        self.assert_catalog_valid()

    def test_concurrent_index_forward_refuses_preexisting_wrong_index(self):
        self.migrate(B1)
        self.migrate(EXPAND)
        self.assertIsNone(catalog_index("uq_option_id_poll"))
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE INDEX uq_option_id_poll ON polls_option (id)"
            )
        try:
            with self.assertRaises(ProgrammingError):
                self.migrate(INDEX)
        finally:
            # Remove only the wrong index this test just created.
            with connection.cursor() as cursor:
                cursor.execute("DROP INDEX uq_option_id_poll")
        self.migrate(LATEST)
        self.assert_catalog_valid()
