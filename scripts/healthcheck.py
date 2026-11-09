"""Health check — exit 0 only if the API and the database are up.

Usage:
    python scripts/healthcheck.py [--url URL] [--expect-version 0.8.0]
                                  [--expect-env production]

Checks GET <url>/health and requires status == "ok" and
database == "connected". With --expect-version / --expect-env it
also verifies the running build is the expected one — useful after a
deploy to prove the new version is actually serving.
"""
import argparse
import json
import sys
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the API health endpoint.")
    parser.add_argument("--url", default="http://127.0.0.1:8100",
                        help="API base URL (default http://127.0.0.1:8100).")
    parser.add_argument("--expect-version", default=None)
    parser.add_argument("--expect-env", default=None)
    args = parser.parse_args()

    url = args.url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - reported, not hidden
        print(f"FAIL: cannot reach {url}: {exc}")
        return 1
    data = payload.get("data", {})
    print(f"status={data.get('status')} version={data.get('version')} "
          f"environment={data.get('environment')} database={data.get('database')}")
    problems = []
    if data.get("status") != "ok":
        problems.append("status is not ok")
    if data.get("database") != "connected":
        problems.append("database is not connected")
    if args.expect_version and data.get("version") != args.expect_version:
        problems.append(
            f"version is {data.get('version')}, expected {args.expect_version}")
    if args.expect_env and data.get("environment") != args.expect_env:
        problems.append(
            f"environment is {data.get('environment')}, expected {args.expect_env}")
    if problems:
        print("FAIL: " + "; ".join(problems))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
