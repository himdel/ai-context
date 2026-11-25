#!/usr/bin/env python3
"""Register report proposals, never submit them. Standard library only."""

import argparse
import ipaddress
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def local_base(value):
    try:
        url = urlsplit(value)
        local = url.hostname == "localhost"
        if not local:
            local = ipaddress.ip_address(url.hostname or "").is_loopback
        if (
            not local
            or url.scheme not in ("http", "https")
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/")
        ):
            raise ValueError
        url.port  # Validate the port before constructing a request.
    except ValueError:
        raise argparse.ArgumentTypeError(
            "Contexts URL must be a loopback HTTP(S) origin."
        ) from None
    return value.rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.URLError(
            "Contexts registration unexpectedly redirected; refusing."
        )


def markdown_label(value):
    return (
        value.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("\n", " ")
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposals", type=Path)
    parser.add_argument(
        "--base-url",
        type=local_base,
        default=os.environ.get("CONTEXTS_URL", "http://localhost:8062"),
    )
    parser.add_argument("--source", choices=["claude", "opencode"])
    parser.add_argument("--conversation")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        data = json.loads(args.proposals.read_text())
        if not isinstance(data, dict):
            raise ValueError("Proposal file must contain a JSON object.")
        current = os.environ.get("OPENCODE_SESSION_ID", "")
        conversation = args.conversation or data.get("conversation_id") or current
        source = (
            args.source
            or data.get("source")
            or ("opencode" if current and conversation == current else "")
        )
        if not conversation or not source:
            raise ValueError(
                "Supply the exact --conversation and --source; no session will be guessed."
            )
        data.update(conversation_id=conversation, source=source)
        request = urllib.request.Request(
            f"{args.base_url}/api/report-actions",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Never send localhost requests through an HTTP proxy or follow redirects.
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )
        with opener.open(request, timeout=30) as response:
            saved = json.load(response)
        if args.json:
            print(json.dumps(saved, indent=2))
        else:
            print(
                "Choose one next step:"
                if saved["mode"] == "exclusive"
                else "Follow-up actions (each once):"
            )
            for action in saved["actions"]:
                print(f"- [{markdown_label(action['label'])}](<{action['url']}>)")
    except urllib.error.HTTPError as exc:
        print(
            f"Could not prepare action links ({exc.code}): {exc.read().decode(errors='replace')}",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
        print(
            f"Could not prepare action links: {exc}. Use plain-text suggestions instead.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
