#!/usr/bin/env python3
"""Submit at most one pinned, pre-verified fork PR per run.

This file only runs on the owner's main branch through a restricted GitHub Action.
It never checks out candidate branches and never runs their code.
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

TARGET = "Chain-Love/chain-love"
SOURCE = "Pepper-46/chain-love"
QUEUE = Path(".github/monetizador/pr-queue.json")
TOKEN = os.getenv("MONETIZADOR_PR_TOKEN", "")
API = "https://api.github.com"


def request(path, method="GET", payload=None):
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "monetizador-safe-pr-publisher",
    }
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(API + path, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=25) as response:
            return json.load(response)
    except HTTPError as exc:
        message = exc.read(1000).decode("utf-8", "replace")
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}: {message}") from None


def main():
    if os.environ.get("GITHUB_REPOSITORY") != SOURCE:
        raise RuntimeError("Unexpected workflow repository; refused")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise RuntimeError("Only the default main branch is allowed")
    if not TOKEN:
        print("MONETIZADOR_PR_TOKEN is not configured. No submission attempted.")
        return

    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    if queue.get("version") != 1:
        raise ValueError("Unknown queue schema version")

    for entry in queue.get("submissions", []):
        if entry.get("enabled") is not True:
            continue
        branch = entry["branch"]
        sha = entry["expected_head_sha"]
        title = entry["title"]
        body = entry["body"]

        if (
            not isinstance(branch, str)
            or not re.fullmatch(r"data/[a-z0-9][a-z0-9._/-]{0,100}", branch)
            or ".." in branch or "//" in branch
            or not re.fullmatch(r"[0-9a-f]{40}", sha)
            or not isinstance(title, str) or not 5 <= len(title) <= 160
            or not isinstance(body, str) or not 20 <= len(body) <= 12000
        ):
            raise ValueError("Invalid or unsafe queue entry")

        query = urlencode({"state": "all", "head": "Pepper-46:" + branch, "per_page": 20})
        existing = request(f"/repos/{TARGET}/pulls?{query}")
        if existing:
            print(f"Already submitted {branch} as PR #{existing[0]['number']}; skipped")
            continue

        info = request(f"/repos/{SOURCE}/branches/{quote(branch, safe='')}")
        actual_sha = info["commit"]["sha"]
        if actual_sha != sha:
            raise RuntimeError(f"Branch {branch} changed since review; skipped")

        # The target repo and head owner are fixed; no arbitrary repo PRs.
        result = request(
            f"/repos/{TARGET}/pulls",
            method="POST",
            payload={
                "title": title,
                "head": "Pepper-46:" + branch,
                "base": "main",
                "body": body,
                "draft": False,
                "maintainer_can_modify": True,
            },
        )
        print(f"Created PR #{result['number']}: {result['html_url']}")
        return  # Limit to one new contribution per run.
    print("No unpublished, approved queue entries.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Publisher failed: {exc}", file=sys.stderr)
        sys.exit(1)
