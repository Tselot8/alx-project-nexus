"""Real Vite fixture lifecycle regressions on the owned integration stack."""

from pathlib import Path
import socket

import pytest
from django.core.cache import cache

from integration import conftest as harness
from polls.models import Category
from scripts.start_local import LocalSetupError, probe_http, NoRedirect
from scripts.verify_fullstack import require_free
from urllib.request import ProxyHandler, build_opener


def observe_children(monkeypatch):
    original = harness.subprocess.Popen
    processes = []

    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(harness.subprocess, "Popen", launch)
    return processes


def test_repeated_owned_vite_setup_and_teardown(live_server, monkeypatch):
    processes = observe_children(monkeypatch)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    paths = []
    for cycle in range(3):
        with harness.managed_stack(live_server) as (base, env):
            process = processes[-1]
            assert process.poll() is None
            artifacts = Path(env["NEXUS_E2E_ARTIFACTS"])
            assert artifacts.is_dir()
            assert artifacts not in paths
            assert all(not previous.exists() for previous in paths)
            paths.append(artifacts)
            ready, reason = probe_http(
                opener,
                base + "/api/v2/auth/csrf/",
                "csrf",
            )
            assert ready, "Live proxy readiness failed: " + reason
            cache.set("fixture-lifecycle-cache", cycle)
        assert process.poll() is not None, "Owned Vite child was not reaped."
        assert not artifacts.exists(), "Owned browser artifacts survived."
        require_free(5181)
    assert len(processes) == 3


def test_readiness_failure_still_reaps_only_the_owned_child(
    live_server,
    monkeypatch,
):
    processes = observe_children(monkeypatch)
    original_wait = harness.wait_for_servers

    def fail_after_listening(*args, **kwargs):
        original_wait(*args, **kwargs)
        raise LocalSetupError("Vite lifecycle readiness regression.")

    monkeypatch.setattr(harness, "wait_for_servers", fail_after_listening)
    with socket.create_server(("127.0.0.1", 0)) as unrelated:
        with pytest.raises(
            pytest.fail.Exception,
            match="lifecycle readiness regression",
        ) as failure:
            with harness.managed_stack(live_server):
                pytest.fail("A failed readiness check yielded a live fixture.")
        assert "Vite (sanitized)" in str(failure.value)
        assert unrelated.fileno() != -1
        with socket.create_connection(
            unrelated.getsockname(),
            timeout=2,
        ):
            with unrelated.accept()[0] as connection:
                assert connection.fileno() != -1
    assert len(processes) == 1
    assert processes[0].poll() is not None
    require_free(5181)


@pytest.mark.parametrize("cycle", range(2))
def test_per_test_database_cache_and_artifacts_remain_isolated(
    full_stack,
    cycle,
):
    _, env = full_stack
    assert Path(env["NEXUS_E2E_ARTIFACTS"]).is_dir()
    assert not Category.objects.filter(
        name="Fixture isolation marker"
    ).exists()
    assert cache.get("fixture-isolation-marker") is None
    Category.objects.create(name="Fixture isolation marker")
    cache.set("fixture-isolation-marker", cycle)
