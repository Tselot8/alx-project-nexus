"""Real-browser WCAG checks, keyboard journeys and responsive QA."""

import os
import subprocess

import pytest
from polls.models import Category


@pytest.mark.parametrize("project", ["qa-desktop", "qa-tablet", "qa-mobile"])
@pytest.mark.parametrize("journey", ["guest routes", "creator forms"])
def test_browser_qa(full_stack, project, journey):
    if os.getenv("NEXUS_INTEGRATION_HTTP_ONLY") == "1":
        pytest.skip("Browser QA explicitly disabled by --http-only.")
    _, env = full_stack
    Category.objects.create(name="Browser topics")
    completed = subprocess.run(
        [
            "node",
            "node_modules/@playwright/test/cli.js",
            "test",
            "--project",
            project,
            "--grep",
            journey,
        ],
        cwd=env["NEXUS_INTEGRATION_FRONTEND_DIR"],
        env=env,
        check=False,
    )
    assert (
        completed.returncode == 0
    ), "Browser QA failed; see safe step diagnostics."
