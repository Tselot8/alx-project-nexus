"""Share capability headers must not enter Django exception reports."""

import re

from django.views.debug import SafeExceptionReporterFilter


class ShareAwareExceptionReporterFilter(SafeExceptionReporterFilter):
    hidden_settings = re.compile(
        SafeExceptionReporterFilter.hidden_settings.pattern + r"|POLL_SHARE",
        re.I,
    )
