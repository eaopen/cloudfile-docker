#!/usr/bin/env python3
"""Refuse a first CLI binding unless the target library is empty."""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def require_empty(server_url, repo_id, token_file):
    parsed = urlsplit(server_url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or
            parsed.query or parsed.fragment):
        raise ValueError("invalid migration server URL")
    with open(token_file, "rb") as stream:
        token = stream.read(4097).strip()
    if not token or len(token) > 4096 or b"\n" in token or b"\r" in token:
        raise ValueError("invalid migration token")
    endpoint = server_url.rstrip("/") + "/api2/repos/" + quote(repo_id, safe="") + "/dir/?p=%2F"
    request = Request(endpoint, headers={"Authorization": "Token " + token.decode("ascii")})
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise ValueError("target library could not be read")
            body = response.read(1024 * 1024 + 1)
    except (HTTPError, URLError, TimeoutError):
        raise ValueError("target library could not be read") from None
    if len(body) > 1024 * 1024:
        raise ValueError("target library listing exceeds preflight limit")
    listing = json.loads(body)
    if not isinstance(listing, list) or listing:
        raise ValueError("target library is not empty")


if __name__ == "__main__":
    try:
        require_empty(os.environ["CF_MIGRATION_SERVER_URL"], os.environ["CF_MIGRATION_REPO_ID"],
                      "/run/secrets/cf_migration_token")
    except (OSError, ValueError, UnicodeError, UnicodeDecodeError, KeyError) as error:
        print("Migration preflight failed: " + str(error), file=sys.stderr)
        sys.exit(2)
