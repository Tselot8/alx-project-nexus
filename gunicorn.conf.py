"""Small single-origin staging process; never migrate or import data."""

import os

from gunicorn.glogging import Logger
from alx_project_nexus.deployment import SafeServerLogFilter


class SafeLogger(Logger):
    def setup(self, cfg):
        super().setup(cfg)
        self.error_log.addFilter(SafeServerLogFilter())


logger_class = SafeLogger

port = int(os.environ.get("PORT", "8000"))
if not 1024 <= port <= 65535:
    raise RuntimeError("PORT must be an unprivileged TCP port.")
bind = f"0.0.0.0:{port}"
workers = 1
worker_class = "gthread"
threads = 2
timeout = 30
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 50

# Django alone evaluates the explicitly approved ingress protocol header.
# Do not let Gunicorn independently trust forwarded headers or IPs.
forwarded_allow_ips = ""
secure_scheme_headers = {}
accesslog = None  # Do not record private capabilities, query strings or users.
errorlog = "-"
loglevel = "warning"
capture_output = False
