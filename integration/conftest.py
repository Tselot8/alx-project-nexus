"""Opt-in live tests; default backend CI needs no Node or browser tools."""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import connection

from scripts.start_local import (
    LocalSetupError,
    sanitized_log,
    stop_owned,
    wait_for_servers,
)

from scripts.verify_fullstack import require_free

ROOT = Path(__file__).resolve().parents[1]


def pytest_configure():
    nonce = os.getenv("NEXUS_INTEGRATION_RUN", "")
    database = settings.DATABASES["default"]
    if (
        not re.fullmatch("[a-f0-9]{12}", nonce)
        or os.getenv("DJANGO_SETTINGS_MODULE")
        != "alx_project_nexus.settings_test"
        or database["HOST"] != "127.0.0.1"
        or str(database["PORT"]) != "55434"
        or database["NAME"] != "nexus_test_i_" + nonce
        or database["USER"] != "nexus_test_i_user_" + nonce
        or settings.EMAIL_BACKEND
        != "django.core.mail.backends.locmem.EmailBackend"
    ):
        raise pytest.UsageError(
            "Use scripts/verify_fullstack.py; "
            "an owned disposable database is required."
        )


@contextmanager
def managed_stack(live_server):
    expected = "test_nexus_test_i_" + os.environ["NEXUS_INTEGRATION_RUN"]
    assert (
        connection.settings_dict["NAME"] == expected
    ), "Refusing a non-test database."
    require_free(5181)
    cache.clear()
    env = os.environ.copy()
    env["NEXUS_PROXY_TARGET"] = live_server.url
    frontend = Path(env["NEXUS_INTEGRATION_FRONTEND_DIR"]).resolve()
    assert frontend == ROOT / "frontend" or (
        frontend.name == "frontend"
        and frontend.parent.name.startswith("nexus-i-frontcheck-")
        and frontend.parent.parent == Path(tempfile.gettempdir()).resolve()
    ), "Unexpected frontend source directory."
    base = "http://127.0.0.1:5181"
    # Vite is owned here; no deployment or static settings are changed.
    node = shutil.which("node")
    assert node, "Node is required for live Vite verification."
    with tempfile.TemporaryDirectory(prefix="nexus-i-browser-") as artifacts:
        with tempfile.TemporaryFile(mode="w+b") as vite_log:
            server = subprocess.Popen(
                [
                    node,
                    str(frontend / "node_modules/vite/bin/vite.js"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "5181",
                ],
                cwd=frontend,
                env=env,
                stdout=vite_log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                # Reuse banner-independent HTTP validation: Django first,
                # Vite's JS endpoint second, then proxied CSRF JSON.
                # live_server is owned by pytest, so only Vite is a child here.
                class LiveDjango:
                    def poll(self):
                        return None

                try:
                    wait_for_servers(
                        [LiveDjango(), server],
                        live_server.url,
                        base,
                    )
                except LocalSetupError as error:
                    stop_owned([server])
                    pytest.fail(
                        str(error)
                        + "\nVite (sanitized):\n"
                        + sanitized_log(vite_log, env)
                    )
                yield base, {
                    **env,
                    "NEXUS_E2E_BASE_URL": base,
                    "NEXUS_E2E_ARTIFACTS": artifacts,
                }
            finally:
                stop_owned([server])


@pytest.fixture
def full_stack(live_server):
    # Keep transactional DB/cache/browser artifacts isolated for every test.
    with managed_stack(live_server) as stack:
        yield stack
