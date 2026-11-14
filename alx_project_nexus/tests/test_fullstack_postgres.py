"""Version-specific full-stack storage must remain disposable and loopback."""

import copy
import unittest
from unittest.mock import patch

from scripts.verify_fullstack import (
    main,
    postgres_runtime,
    validate_database_container,
)


class PostgresRunnerTests(unittest.TestCase):
    def container_info(self, destination):
        return {
            "HostConfig": {
                "PortBindings": {
                    "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "55434"}],
                },
                "Tmpfs": {destination: "rw"},
            },
            "Mounts": [],
        }

    def test_both_image_layouts_have_the_required_tmpfs_root(self):
        for major, destination in (
            (15, "/var/lib/postgresql/data"),
            (18, "/var/lib/postgresql"),
        ):
            with self.subTest(major=major):
                image, root = postgres_runtime(major)
                self.assertEqual(image, f"postgres:{major}")
                self.assertEqual(root, destination)
                validate_database_container(self.container_info(root), root)

    def test_pg18_rejects_old_layout_and_persistent_mounts(self):
        root = postgres_runtime(18)[1]
        info = self.container_info(root)
        mutations = []
        wrong_root = copy.deepcopy(info)
        wrong_root["HostConfig"]["Tmpfs"] = {"/var/lib/postgresql/data": "rw"}
        mutations.append(wrong_root)
        for kind in ("volume", "bind"):
            persistent = copy.deepcopy(info)
            persistent["Mounts"] = [{"Type": kind}]
            mutations.append(persistent)
        for changed in mutations:
            with self.subTest(info=changed), self.assertRaises(RuntimeError):
                validate_database_container(changed, root)

    def test_non_loopback_or_wrong_port_is_rejected(self):
        root = postgres_runtime(18)[1]
        for binding in (
            [{"HostIp": "0.0.0.0", "HostPort": "55434"}],
            [{"HostIp": "127.0.0.1", "HostPort": "5432"}],
        ):
            info = self.container_info(root)
            info["HostConfig"]["PortBindings"]["5432/tcp"] = binding
            with self.subTest(binding=binding):
                with self.assertRaises(RuntimeError):
                    validate_database_container(info, root)

    def test_unsupported_version_stops_before_docker(self):
        args = ["verify_fullstack.py", "--postgres-major", "17"]
        with patch("sys.argv", args):
            target = "scripts.verify_fullstack.subprocess.run"
            with patch(target) as run:
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()
        with self.assertRaises(ValueError):
            postgres_runtime(17)
