"""Schema constraints and model validation on disposable PostgreSQL."""

from hashlib import sha256
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from polls.models import (
    Ballot,
    BallotSelection,
    Option,
    Poll,
    PollShareToken,
    Vote,
)

POLL_CHECKS = {
    "ck_poll_status",
    "ck_poll_results_vis",
    "ck_poll_min_sel",
    "ck_poll_max_sel",
    "ck_poll_single_limits",
    "ck_poll_version",
}
COMPOSITE_FKS = {
    "fk_selection_ballot_poll": (
        ["ballot_id", "poll_id"],
        "polls_ballot",
        ["id", "poll_id"],
    ),
    "fk_selection_option_poll": (
        ["option_id", "poll_id"],
        "polls_option",
        ["id", "poll_id"],
    ),
}


def catalog_constraints(table):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.conname, c.contype, c.convalidated,
                   c.condeferrable, c.condeferred,
                   ARRAY(
                       SELECT a.attname
                       FROM unnest(c.conkey) WITH ORDINALITY AS k(num, pos)
                       JOIN pg_attribute a ON a.attrelid = c.conrelid
                           AND a.attnum = k.num
                       ORDER BY k.pos
                   ),
                   CASE WHEN c.contype = 'f'
                        THEN c.confrelid::regclass::text ELSE NULL END,
                   ARRAY(
                       SELECT a.attname
                       FROM unnest(c.confkey) WITH ORDINALITY AS k(num, pos)
                       JOIN pg_attribute a ON a.attrelid = c.confrelid
                           AND a.attnum = k.num
                       ORDER BY k.pos
                   )
            FROM pg_constraint c
            WHERE c.conrelid = to_regclass(%s)
        """,
            [table],
        )
        return {
            row[0]: {
                "type": row[1],
                "validated": row[2],
                "deferrable": row[3],
                "deferred": row[4],
                "columns": row[5],
                "target": row[6],
                "target_columns": row[7],
            }
            for row in cursor.fetchall()
        }


def catalog_index(name):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT i.indisunique, i.indisvalid, i.indisready,
                   pg_get_indexdef(i.indexrelid)
            FROM pg_index i
            WHERE i.indexrelid = to_regclass(%s)
        """,
            [name],
        )
        return cursor.fetchone()


class SchemaModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="schema@example.invalid",
            username="schema",
            password=None,
        )
        cls.poll = Poll.objects.create(
            question="Schema question?",
            created_by=cls.user,
        )
        cls.other = Poll.objects.create(
            question="Other poll?",
            created_by=cls.user,
        )
        cls.option = Option.objects.create(
            poll=cls.poll,
            option_text="First",
        )
        cls.other_option = Option.objects.create(
            poll=cls.other,
            option_text="Other",
        )

    def assert_db_rejected(self, action, constraint=None):
        with self.assertRaises(IntegrityError) as raised:
            with transaction.atomic():
                action()
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        if constraint:
            self.assertEqual(
                raised.exception.__cause__.diag.constraint_name, constraint
            )

    def test_dormant_defaults_and_explicit_lock_states(self):
        self.poll.refresh_from_db()
        self.assertEqual(self.poll.status, "published")
        self.assertEqual(self.poll.results_visibility, "immediate")
        self.assertEqual(self.poll.min_selections, 1)
        self.assertIsNone(self.poll.max_selections)
        self.assertEqual(self.poll.version, 1)
        self.assertIsNone(self.poll.configuration_locked)
        for value in (False, True, None):
            self.poll.configuration_locked = value
            self.poll.save(update_fields=["configuration_locked"])
            self.poll.refresh_from_db()
            self.assertIs(self.poll.configuration_locked, value)

    def test_poll_model_validation_has_field_errors(self):
        cases = [
            ({"status": "bad"}, "status"),
            ({"results_visibility": "bad"}, "results_visibility"),
            ({"min_selections": 0}, "min_selections"),
            (
                {
                    "allow_multiple": True,
                    "min_selections": 2,
                    "max_selections": 1,
                },
                "max_selections",
            ),
            ({"max_selections": 2}, "allow_multiple"),
            ({"version": 0}, "version"),
        ]
        for changes, field in cases:
            with self.subTest(changes=changes):
                candidate = Poll(
                    question="Valid?", created_by=self.user, **changes
                )
                with self.assertRaises(ValidationError) as raised:
                    candidate.full_clean()
                self.assertIn(field, raised.exception.message_dict)

    def test_all_named_poll_checks_reject_raw_updates(self):
        cases = [
            ({"status": "bad"}, "ck_poll_status"),
            ({"results_visibility": "bad"}, "ck_poll_results_vis"),
            ({"min_selections": 0, "allow_multiple": True}, "ck_poll_min_sel"),
            ({"allow_multiple": True, "max_selections": 0}, "ck_poll_max_sel"),
            ({"max_selections": 2}, "ck_poll_single_limits"),
            ({"version": 0}, "ck_poll_version"),
        ]
        before = Poll.objects.values().get(pk=self.poll.pk)
        for changes, name in cases:
            with self.subTest(changes=changes):
                self.assert_db_rejected(
                    lambda changes=changes: Poll.objects.filter(
                        pk=self.poll.pk
                    ).update(**changes),
                    name,
                )
                self.assertEqual(
                    Poll.objects.values().get(pk=self.poll.pk), before
                )

    def test_pending_ballot_is_not_a_submission_and_source_is_validated(self):
        ballot = Ballot.objects.create(poll=self.poll, user=self.user)
        self.assertIsNone(ballot.submitted_at)
        ballot.full_clean()
        ballot.source = "bad"
        with self.assertRaises(ValidationError) as raised:
            ballot.full_clean()
        self.assertIn("source", raised.exception.message_dict)
        self.assert_db_rejected(
            lambda: Ballot.objects.filter(pk=ballot.pk).update(source="bad"),
            "ck_ballot_source",
        )

    def test_ballot_uniqueness_is_database_enforced(self):
        Ballot.objects.create(poll=self.poll, user=self.user)
        self.assert_db_rejected(
            lambda: Ballot.objects.create(poll=self.poll, user=self.user),
            "uq_ballot_poll_user",
        )

    def test_submitted_ballot_requires_persisted_nonempty_selections(self):
        candidate = Ballot(
            poll=self.poll, user=self.user, submitted_at=timezone.now()
        )
        with self.assertRaises(ValidationError):
            candidate.full_clean()
        ballot = Ballot.objects.create(poll=self.poll, user=self.user)
        ballot.submitted_at = timezone.now()
        with self.assertRaises(ValidationError):
            ballot.full_clean()
        BallotSelection.objects.create(
            ballot=ballot, poll=self.poll, option=self.option
        )
        ballot.full_clean()
        ballot.save(update_fields=["submitted_at", "updated_at"])
        self.assertFalse(Vote.objects.exists())

    def test_multiple_choice_cardinality_validation_uses_persisted_selections(
        self,
    ):
        self.poll.allow_multiple = True
        self.poll.min_selections = 2
        self.poll.max_selections = 2
        self.poll.save()
        options = [
            self.option,
            Option.objects.create(poll=self.poll, option_text="Second"),
            Option.objects.create(poll=self.poll, option_text="Third"),
        ]
        ballot = Ballot.objects.create(poll=self.poll, user=self.user)
        ballot.submitted_at = timezone.now()
        for index, option in enumerate(options):
            BallotSelection.objects.create(
                ballot=ballot, poll=self.poll, option=option
            )
            if index == 1:
                ballot.full_clean()
            else:
                with self.assertRaises(ValidationError):
                    ballot.full_clean()

    def test_null_maximum_means_available_options_for_multiple_choice(self):
        self.poll.allow_multiple = True
        self.poll.save(update_fields=["allow_multiple"])
        ballot = Ballot.objects.create(poll=self.poll, user=self.user)
        BallotSelection.objects.create(
            ballot=ballot, poll=self.poll, option=self.option
        )
        ballot.submitted_at = timezone.now()
        ballot.full_clean()

    def test_selection_model_validation_reports_both_parent_mismatches(self):
        ballot = Ballot.objects.create(poll=self.poll, user=self.user)
        selection = BallotSelection(
            ballot=ballot, poll=self.other, option=self.option
        )
        with self.assertRaises(ValidationError) as raised:
            selection.full_clean()
        self.assertIn("poll", raised.exception.message_dict)
        self.assertIn("option", raised.exception.message_dict)

    def test_selection_uniqueness_is_database_enforced(self):
        ballot = Ballot.objects.create(poll=self.poll, user=self.user)
        BallotSelection.objects.create(
            ballot=ballot, poll=self.poll, option=self.option
        )
        self.assert_db_rejected(
            lambda: BallotSelection.objects.create(
                ballot=ballot, poll=self.poll, option=self.option
            ),
            "uq_selection_ballot_option",
        )

    def test_cross_poll_bulk_insert_is_rejected_at_constraint_check(self):
        ballot = Ballot.objects.create(poll=self.poll, user=self.user)
        for poll, option, name in (
            (self.poll, self.other_option, "fk_selection_option_poll"),
            (self.other, self.other_option, "fk_selection_ballot_poll"),
        ):
            with self.subTest(constraint=name):
                selections = BallotSelection.objects
                self.assert_db_rejected(
                    lambda poll=poll, option=option: selections.bulk_create(
                        [
                            BallotSelection(
                                ballot=ballot, poll=poll, option=option
                            )
                        ]
                    ),
                    name,
                )
                self.assertFalse(BallotSelection.objects.exists())

    def test_cross_poll_raw_insert_is_rejected(self):
        ballot = Ballot.objects.create(poll=self.poll, user=self.user)

        def insert():
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO polls_ballotselection "
                    "(id, ballot_id, poll_id, option_id) "
                    "VALUES (%s, %s, %s, %s)",
                    [
                        uuid.uuid4(),
                        ballot.pk,
                        self.poll.pk,
                        self.other_option.pk,
                    ],
                )

        self.assert_db_rejected(insert, "fk_selection_option_poll")

    def test_parent_reparenting_cannot_break_composite_membership(self):
        ballot = Ballot.objects.create(poll=self.poll, user=self.user)
        BallotSelection.objects.create(
            ballot=ballot, poll=self.poll, option=self.option
        )
        self.assert_db_rejected(
            lambda: Option.objects.filter(pk=self.option.pk).update(
                poll=self.other
            ),
            "fk_selection_option_poll",
        )
        self.assert_db_rejected(
            lambda: Ballot.objects.filter(pk=ballot.pk).update(
                poll=self.other
            ),
            "fk_selection_ballot_poll",
        )

    def test_participation_protects_user_poll_and_option_deletion(self):
        ballot = Ballot.objects.create(poll=self.poll, user=self.user)
        BallotSelection.objects.create(
            ballot=ballot, poll=self.poll, option=self.option
        )
        for obj in (self.user, self.poll, self.option):
            with self.subTest(model=type(obj).__name__):
                with self.assertRaises(ProtectedError):
                    obj.delete()

    def test_incomplete_ballot_deletion_cascades_its_staging_selections(self):
        ballot = Ballot.objects.create(poll=self.poll, user=self.user)
        BallotSelection.objects.create(
            ballot=ballot, poll=self.poll, option=self.option
        )
        ballot.delete()
        self.assertFalse(BallotSelection.objects.exists())

    def test_digest_storage_defaults_uniqueness_and_nullable_inactive_rows(
        self,
    ):
        first = PollShareToken.objects.create(poll=self.poll)
        second = PollShareToken.objects.create(poll=self.other)
        self.assertIsNone(first.token_digest)
        self.assertEqual(first.generation, 1)
        raw_fixture = "non-secret test fixture, not an issued share token"
        digest = sha256(raw_fixture.encode()).hexdigest()
        first.token_digest = digest
        first.full_clean()
        first.save()
        first.refresh_from_db()
        self.assertEqual(first.token_digest, digest)
        self.assertNotEqual(first.token_digest, raw_fixture)
        self.assert_db_rejected(
            lambda: PollShareToken.objects.filter(pk=second.pk).update(
                token_digest=digest
            ),
            "uq_share_digest",
        )

    def test_invalid_digests_and_generation_rejected_by_model_and_database(
        self,
    ):
        for digest in ("", "a" * 63, "A" * 64, "g" * 64):
            with self.subTest(digest_shape=digest[:3]):
                row = PollShareToken(poll=self.poll, token_digest=digest)
                with self.assertRaises(ValidationError) as raised:
                    row.full_clean()
                self.assertIn("token_digest", raised.exception.message_dict)
                self.assert_db_rejected(
                    lambda digest=digest: PollShareToken.objects.create(
                        poll=self.poll, token_digest=digest
                    ),
                    "ck_share_digest",
                )
        row = PollShareToken(poll=self.poll, generation=0)
        with self.assertRaises(ValidationError) as raised:
            row.full_clean()
        self.assertIn("generation", raised.exception.message_dict)
        self.assert_db_rejected(
            lambda: PollShareToken.objects.create(
                poll=self.poll, generation=0
            ),
            "ck_share_generation",
        )

    def test_postgresql_catalog_has_validated_composite_and_ordinary_fks(self):
        self.assertEqual(connection.vendor, "postgresql")
        constraints = catalog_constraints("polls_ballotselection")
        for name, (columns, target, target_columns) in COMPOSITE_FKS.items():
            actual = constraints[name]
            self.assertEqual(actual["type"], "f")
            self.assertTrue(actual["validated"])
            self.assertTrue(actual["deferrable"])
            self.assertTrue(actual["deferred"])
            self.assertEqual(actual["columns"], columns)
            self.assertEqual(actual["target"], target)
            self.assertEqual(actual["target_columns"], target_columns)
        single_fks = {
            tuple(row["columns"])
            for row in constraints.values()
            if row["type"] == "f"
        }
        self.assertTrue(
            {
                ("ballot_id",),
                ("poll_id",),
                ("option_id",),
            }.issubset(single_fks)
        )
        for name in POLL_CHECKS:
            self.assertTrue(
                catalog_constraints("polls_poll")[name]["validated"]
            )
        index = catalog_index("uq_option_id_poll")
        self.assertEqual(index[:3], (True, True, True))
        self.assertIn("(id, poll_id)", index[3])
        self.assertEqual(
            catalog_constraints("polls_option")["uq_option_id_poll"]["type"],
            "u",
        )
        self.assertTrue(catalog_index("idx_selection_poll_option")[1])
