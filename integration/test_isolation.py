"""Fail-closed harness guards; no database or container operations."""

import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "nexus_integration_runner",
    Path(__file__).resolve().parents[1] / "scripts/verify_fullstack.py",
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_remote_docker_override_rejected_before_any_command(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://not-a-local-engine.invalid:2375")
    monkeypatch.setattr(
        "sys.argv", ["verify_fullstack.py", "--integration-only"]
    )

    def unexpected(*args, **kwargs):
        pytest.fail("A Docker command ran before remote-context rejection.")

    monkeypatch.setattr(runner.subprocess, "check_output", unexpected)
    with pytest.raises(RuntimeError, match="Clear Docker endpoint overrides"):
        runner.main()


def test_cleanup_rejects_a_container_without_the_current_ownership_nonce():
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "Config": {
                            "Labels": {
                                "project-nexus.integration": "other-run"
                            }
                        },
                    }
                ]
            ),
        )

    with pytest.raises(RuntimeError, match="ownership mismatch"):
        runner.cleanup_database(
            docker, "nexus-i-unit", "current-run", set(), set(), set()
        )
    assert [call[0] for call in calls] == ["inspect"]


def test_occupied_port_is_rejected_without_stopping_its_listener():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with pytest.raises(RuntimeError, match="occupied"):
            runner.require_free(port)
        assert listener.fileno() != -1
