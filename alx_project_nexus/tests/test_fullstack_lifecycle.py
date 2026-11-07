"""Real socket lifecycle checks without database or server dependencies."""

import os
from pathlib import Path
import socket
import sys
import unittest

from scripts.verify_fullstack import require_free


def listener(port=0):
    # Match Node/POSIX server reuse semantics, without Windows port sharing.
    return socket.create_server(("127.0.0.1", port))


def close_connection_from_server(server):
    """Complete an active close so Linux retains the server-side TIME_WAIT."""
    port = server.getsockname()[1]
    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
        with server.accept()[0] as accepted:
            accepted.settimeout(2)
            accepted.shutdown(socket.SHUT_WR)
            if client.recv(1) != b"":
                raise AssertionError("Expected server FIN.")
            client.shutdown(socket.SHUT_WR)
            if accepted.recv(1) != b"":
                raise AssertionError("Expected client FIN.")


class FullstackPortLifecycleTests(unittest.TestCase):
    def test_live_listener_is_rejected_and_keeps_serving(self):
        with listener() as server:
            port = server.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError, "occupied"):
                require_free(port)
            with socket.create_connection(
                ("127.0.0.1", port), timeout=2
            ) as client:
                with server.accept()[0] as accepted:
                    accepted.sendall(b"still-owned")
                    self.assertEqual(client.recv(32), b"still-owned")

    def test_owned_wildcard_listener_is_also_rejected(self):
        with socket.socket() as server:
            if os.name == "nt":
                # Windows requires the wildcard owner to reserve its range.
                # Non-exclusive wildcards intentionally permit specific binds.
                server.setsockopt(
                    socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
                )
            server.bind(("0.0.0.0", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError, "occupied"):
                require_free(port)
            self.assertNotEqual(server.fileno(), -1)

    def test_closed_listener_with_time_wait_is_available(self):
        with listener() as server:
            port = server.getsockname()[1]
            close_connection_from_server(server)
        if sys.platform.startswith("linux"):
            entries = Path("/proc/net/tcp").read_text().splitlines()[1:]
            self.assertTrue(
                any(
                    row.split()[1].endswith(":%04X" % port)
                    and row.split()[3] == "06"
                    for row in entries
                ),
                "The regression must actually create Linux TIME_WAIT.",
            )
            with socket.socket() as old_probe:
                with self.assertRaises(OSError):
                    old_probe.bind(("127.0.0.1", port))
        require_free(port)
        with listener(port) as replacement:
            self.assertEqual(replacement.getsockname()[1], port)

    def test_repeated_setup_and_complete_teardown_reuse_same_port(self):
        with listener() as initial:
            port = initial.getsockname()[1]
        for cycle in range(5):
            with self.subTest(cycle=cycle):
                require_free(port)
                with listener(port) as server:
                    close_connection_from_server(server)
                require_free(port)


if __name__ == "__main__":
    unittest.main()
