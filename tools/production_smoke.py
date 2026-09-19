"""Post-deployment checks for the public, unauthenticated Studio surface."""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


MINIMUM_VERSION = (9, 2, 1)


def _version(value: object) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in str(value).split("."))
    except (TypeError, ValueError):
        return ()


def validate_health(payload: dict, expected_commit: str = "") -> list[str]:
    errors: list[str] = []
    if payload.get("ok") is not True:
        errors.append("health.ok is not true")
    if payload.get("publicationMode") != "manual-only":
        errors.append("publicationMode must be manual-only")
    if _version(payload.get("version")) < MINIMUM_VERSION:
        errors.append(f"version {payload.get('version')!r} is older than 9.2.1")
    deployed = str(payload.get("releaseCommit") or "")
    expected = expected_commit.strip()
    if expected and not (deployed and expected.startswith(deployed)):
        errors.append(f"release commit {deployed or 'missing'} does not match {expected[:12]}")
    return errors


def validate_homepage(html: str) -> list[str]:
    text = html.lower()
    errors: list[str] = []
    if "prêt pour publication manuelle" not in text:
        errors.append("manual-publication stop is not visible on the homepage")
    for forbidden in ("publication automatique activée", "auto-publish enabled"):
        if forbidden in text:
            errors.append(f"forbidden automatic-publication marker found: {forbidden}")
    return errors


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AutoDirectorProductionSmoke/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def check(base_url: str, expected_commit: str = "") -> list[str]:
    base = base_url.rstrip("/")
    health = json.loads(_get(base + "/health").decode("utf-8"))
    homepage = _get(base + "/").decode("utf-8", errors="replace")
    return validate_health(health, expected_commit) + validate_homepage(homepage)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-commit", default="")
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args()
    deadline = time.monotonic() + max(0, args.wait_seconds)
    last_errors = ["deployment not checked"]
    while True:
        try:
            last_errors = check(args.url, args.expected_commit)
            if not last_errors:
                print("Production smoke test passed: manual-only release is healthy.")
                return 0
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            last_errors = [str(exc)]
        if time.monotonic() >= deadline:
            print("Production smoke test failed: " + "; ".join(last_errors))
            return 1
        time.sleep(15)


if __name__ == "__main__":
    raise SystemExit(main())
