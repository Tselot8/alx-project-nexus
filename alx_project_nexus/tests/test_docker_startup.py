"""The normal staging image must start Django without a dashboard override."""

import json
from pathlib import Path
import unittest


class DockerStartupTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2]
        self.instructions = [
            line.strip()
            for line in (root / "Dockerfile.staging").read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def test_django_default_is_an_exec_form_command_with_separate_arguments(
        self,
    ):
        commands = [
            line.split(None, 1)[1]
            for line in self.instructions
            if line.split(None, 1)[0].upper() == "CMD"
        ]
        self.assertEqual(len(commands), 1)
        self.assertEqual(
            json.loads(commands[0]),
            [
                "gunicorn",
                "-c",
                "gunicorn.conf.py",
                "alx_project_nexus.wsgi:application",
            ],
        )

    def test_no_dockerfile_entrypoint_reinterprets_the_default_command(self):
        self.assertFalse(
            any(
                line.split(None, 1)[0].upper() == "ENTRYPOINT"
                for line in self.instructions
            )
        )
