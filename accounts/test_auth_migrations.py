"""Upgrade preserves existing credentials; tests run on disposable PG only."""

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class AccountMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_users_profiles_passwords_and_old_writers(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertTrue(
            connection.settings_dict["NAME"].startswith("test_nexus_test_")
        )
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [("accounts", "0001_initial")]
        try:
            executor.migrate(previous)
            old = executor.loader.project_state(previous).apps
            User = old.get_model("accounts", "User")
            user = User.objects.create(
                username="before-d",
                email="before-d@example.invalid",
                password=make_password("not-an-actual-user-password"),
                date_joined=timezone.now(),
            )
            old.get_model("accounts", "UserProfile").objects.create(
                user=user, bio="Existing private profile"
            )
            original = User.objects.values().get(pk=user.pk)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            current = executor.loader.project_state(latest).apps
            CurrentUser = current.get_model("accounts", "User")
            migrated = CurrentUser.objects.values().get(pk=user.pk)
            self.assertEqual(migrated.pop("auth_version"), 1)
            self.assertEqual(migrated, original)
            self.assertEqual(
                current.get_model("accounts", "UserProfile")
                .objects.get(user_id=user.pk)
                .bio,
                "Existing private profile",
            )
            # Historical code does not name auth_version; DB default covers it.
            inserted = User.objects.create(
                username="old-writer",
                email="old-writer@example.invalid",
                password="!",
            )
            self.assertEqual(
                CurrentUser.objects.get(pk=inserted.pk).auth_version, 1
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT convalidated FROM pg_constraint "
                    "WHERE conname = 'ck_user_auth_version' "
                    "AND conrelid = 'accounts_user'::regclass"
                )
                self.assertEqual(cursor.fetchone(), (True,))
        finally:
            MigrationExecutor(connection).migrate(latest)
