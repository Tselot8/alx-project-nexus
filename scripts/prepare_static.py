"""Build only collected static assets with synthetic offline settings.

The Docker build calls this explicitly; it never migrates or contacts a DB.
"""

import os
from pathlib import Path
import sys


def main():
    from scripts.check_release import synthetic_environment

    env = synthetic_environment()
    os.environ.clear()
    os.environ.update(env)
    os.environ["NEXUS_SERVE_FRONTEND"] = "false"
    import dotenv

    dotenv.load_dotenv = lambda *args, **kwargs: False
    import socket

    def forbidden(*args, **kwargs):
        raise RuntimeError("Static preparation cannot contact services.")

    socket.socket.connect = forbidden
    socket.socket.connect_ex = forbidden
    socket.create_connection = forbidden
    import django
    from django.db.backends.base.base import BaseDatabaseWrapper

    BaseDatabaseWrapper.connect = forbidden
    django.setup()
    from django.core.management import call_command

    from django.test import override_settings

    root = Path(__file__).resolve().parents[1] / "static-build"
    with override_settings(STATIC_ROOT=root):
        call_command("collectstatic", interactive=False, verbosity=0)
    if not (root / "admin/css/base.css").is_file():
        raise RuntimeError("Collected static artifact is incomplete.")
    print("Static artifact prepared without service access.")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        main()
    except Exception:
        print("Static artifact preparation failed.", file=sys.stderr)
        sys.exit(1)
