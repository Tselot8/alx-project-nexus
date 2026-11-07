"""Opt-in single-origin artifact serving and credential-safe health checks."""

from html.parser import HTMLParser
import logging
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.http import (
    FileResponse,
    Http404,
    HttpResponseRedirect,
    JsonResponse,
)
from django.views.decorators.http import require_safe
from whitenoise.middleware import WhiteNoiseMiddleware


def frontend_settings(env, base, isolated):
    raw = env.get("NEXUS_SERVE_FRONTEND", "false")
    if raw not in {"true", "false"}:
        raise ImproperlyConfigured(
            "NEXUS_SERVE_FRONTEND must be true or false."
        )
    enabled = raw == "true" and not isolated
    root = Path(env.get("NEXUS_FRONTEND_DIST", str(base / "frontend/dist")))
    if enabled:
        validate_artifact(root)
    return {
        "NEXUS_SERVE_FRONTEND": enabled,
        "NEXUS_FRONTEND_DIST": root,
    }


def validate_artifact(root):
    """Require an immutable public build, not an arbitrary directory."""
    if not root.is_absolute() or (
        not (root / "index.html").is_file()
        or (root / "index.html").is_symlink()
    ):
        raise ImproperlyConfigured("A built frontend artifact is required.")
    assets = root / "assets"
    allowed = {".js", ".css", ".svg", ".png", ".jpg", ".webp", ".woff2"}
    if assets.is_symlink() or not assets.is_dir() or not any(assets.iterdir()):
        raise ImproperlyConfigured("Frontend assets are missing.")
    for path in assets.rglob("*"):
        if (
            path.is_symlink()
            or any(
                part.startswith(".") for part in path.relative_to(root).parts
            )
            or (path.is_file() and path.suffix not in allowed)
        ):
            raise ImproperlyConfigured("Unexpected frontend build asset.")

    class References(HTMLParser):
        def __init__(self):
            super().__init__()
            self.urls = []

        def handle_starttag(self, tag, attrs):
            if tag in {"script", "link"}:
                self.urls.extend(
                    value
                    for key, value in attrs
                    if key in {"src", "href"} and value
                )

    parser = References()
    parser.feed((root / "index.html").read_text(encoding="utf-8"))
    if not parser.urls or any(
        not url.startswith("/assets/")
        or "?" in url
        or "#" in url
        or "\\" in url
        or not (root / url[1:]).resolve().is_relative_to(assets.resolve())
        or not (root / url[1:]).is_file()
        for url in parser.urls
    ):
        raise ImproperlyConfigured("Frontend asset references are invalid.")


class ArtifactMiddleware(WhiteNoiseMiddleware):
    """Serve collected static and the public Vite assets directory."""

    def __init__(self, get_response):
        super().__init__(get_response)
        if settings.NEXUS_SERVE_FRONTEND:
            root = settings.NEXUS_FRONTEND_DIST
            validate_artifact(root)
            self.add_files(root / "assets", prefix="assets/")

    def __call__(self, request):
        # Validate Host before static responses bypass Django views.
        request.get_host()
        return super().__call__(request)


class SafeServerLogFilter(logging.Filter):
    """Emit status metadata, excluding paths, headers, bodies and traceback."""

    def filter(self, record):
        status = getattr(record, "status_code", None)
        record.msg = (
            "HTTP response status=%s" % status
            if isinstance(status, int)
            else "Server event; inspect health and operator evidence."
        )
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def health_response(ready, status=200):
    response = JsonResponse({"status": ready}, status=status)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_safe
def live(request):
    # No user, migration, configuration or database information.
    return health_response("ok")


@require_safe
def ready(request):
    try:
        # Bounded read-only SQL; never migrates or authorizes voting cutover.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SET LOCAL statement_timeout = '2s'")
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    return health_response("unavailable", 503)
                executor = MigrationExecutor(connection)
                if executor.migration_plan(executor.loader.graph.leaf_nodes()):
                    return health_response("unavailable", 503)
    except DatabaseError:
        return health_response("unavailable", 503)
    return health_response("ok")


@require_safe
def frontend(request, path=""):
    if not settings.NEXUS_SERVE_FRONTEND:
        raise Http404
    # Reserved namespaces must never become a successful HTML API fallback.
    head = path.split("/", 1)[0].lower()
    if (
        head
        in {
            "api",
            "admin",
            "static",
            "assets",
            "health",
            "swagger",
            "redoc",
        }
        or any("." in part for part in path.split("/"))
        or "\\" in path
    ):
        raise Http404
    response = FileResponse(
        (settings.NEXUS_FRONTEND_DIST / "index.html").open("rb"),
        content_type="text/html; charset=utf-8",
    )
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_safe
def landing(request):
    if not settings.NEXUS_SERVE_FRONTEND:
        return HttpResponseRedirect("/swagger/")
    return frontend(request)
