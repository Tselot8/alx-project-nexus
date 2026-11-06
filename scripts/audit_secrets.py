"""Audit secret exposure, emitting metadata only and never values."""

import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
KEYS = (
    r"POSTGRES_PASSWORD|NEXUS_EMAIL_HOST_PASSWORD|DJANGO_SECRET_KEY|"
    r"SECRET_KEY|API_KEY|ACCESS_TOKEN"
)
ASSIGN = re.compile(r"(?:" + KEYS + r")[\"']?\s*[:=]\s*(.+)")
FIXTURE = re.compile(
    r"(?:fixture|synthetic|non-secret|isolated-test|test-secret|canary)", re.I
)


def classify(path, line):
    stripped = line.strip()
    if stripped.startswith("#"):
        return None
    if re.search(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
        line,
    ):
        return "private_key"
    if re.search(r"\becho\s.*(?:DJANGO_SECRET_KEY|POSTGRES_PASSWORD)", line):
        return "secret_logging"
    match = ASSIGN.search(line)
    if not match:
        return None
    raw = match.group(1).strip().rstrip(",")
    quoted = raw.startswith(('"', "'"))
    value = raw.strip("\"'")
    if not value or (not quoted and value in {"None", "False", "True"}):
        return None
    if value.startswith("${"):
        return None
    python_source = path.endswith(".py") or (
        path.startswith(".github/workflows/")
        and line.rstrip().endswith(",")
        and line.lstrip().startswith(('"', "'"))
    )
    if (
        not quoted
        and python_source
        and (
            value in {"password", "secret"}
            or value.startswith(
                (
                    "env[",
                    "os.",
                    "secrets.",
                    "_required(",
                    "required(",
                    "settings.",
                    "getattr(",
                    "database[",
                )
            )
        )
    ):
        return None
    if ("test" in Path(path).name or "tests/" in path) and FIXTURE.search(
        value
    ):
        return None
    if value.startswith(("<", "[redacted]")):
        return None
    return "credential_literal"


def findings(path, text, revision=None):
    rows = []
    if Path(path).name in {".env", ".env.local", ".env.production"}:
        rows.append(
            {"path": path, "kind": "sensitive_file", "revision": revision}
        )
    for number, line in enumerate(text.splitlines(), 1):
        kind = classify(path, line)
        if kind:
            rows.append(
                {
                    "path": path,
                    "line": number,
                    "kind": kind,
                    "revision": revision,
                }
            )
    return rows


def scan(history=False):
    rows = []
    if history:
        revisions = subprocess.check_output(
            ["git", "rev-list", "--all"], cwd=ROOT, text=True
        ).splitlines()
        for revision in revisions:
            names = subprocess.check_output(
                ["git", "ls-tree", "-r", "--name-only", revision],
                cwd=ROOT,
                text=True,
            ).splitlines()
            for name in names:
                if Path(name).name in {
                    ".env",
                    ".env.local",
                    ".env.production",
                }:
                    rows.append(
                        {
                            "path": name,
                            "kind": "sensitive_file",
                            "revision": revision[:12],
                        }
                    )
            result = subprocess.run(
                [
                    "git",
                    "grep",
                    "-I",
                    "-n",
                    "-E",
                    KEYS + "|PRIVATE KEY-----",
                    revision,
                    "--",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode not in (0, 1):
                raise RuntimeError("History scan failed.")
            for line in result.stdout.splitlines():
                _, path, number, source = line.split(":", 3)
                kind = classify(path, source)
                if kind:
                    rows.append(
                        {
                            "path": path,
                            "line": int(number),
                            "kind": kind,
                            "revision": revision[:12],
                        }
                    )
    else:
        names = (
            subprocess.check_output(
                [
                    "git",
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "-z",
                ],
                cwd=ROOT,
            )
            .decode()
            .split("\0")
        )
        for name in sorted(set(names) - {""}):
            path = ROOT / name
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            rows.extend(findings(name, text))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    rows = scan(args.history)
    print(
        json.dumps(
            {
                "scope": "history" if args.history else "working_tree",
                "findings": rows,
            },
            sort_keys=True,
        )
    )
    return 1 if rows else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError):
        print(
            "Secret audit could not complete; "
            "inspect repository access privately."
        )
        raise SystemExit(2)
