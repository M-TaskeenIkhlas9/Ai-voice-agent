#!/usr/bin/env python3
"""Create or update the Vapi assistant from code, and attach it to a phone number.

Usage (from the repo root, with env vars set; see .env.example):

    python scripts/setup_vapi.py --dry-run            # print the assistant JSON
    python scripts/setup_vapi.py                      # create/update assistant
    python scripts/setup_vapi.py --buy-number 512     # also provision a free Vapi US number
    python scripts/setup_vapi.py --phone-number-id <id>  # attach to an existing number

Idempotent: the assistant is matched by name (or VAPI_ASSISTANT_ID) and
PATCHed in place, so re-run it after every prompt/tool change.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.voice.assistant import ASSISTANT_NAME, build_assistant_config  # noqa: E402

VAPI_BASE = "https://api.vapi.ai"


def _load_dotenv() -> None:
    """Minimal .env loader so the script works without extra dependencies."""
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"error: {name} is not set (see .env.example)")
    return value


def _check(res: httpx.Response, action: str) -> dict:
    if res.status_code >= 400:
        sys.exit(f"error: {action} failed ({res.status_code}): {res.text}")
    return res.json()


def main() -> None:
    _load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print assistant JSON and exit")
    parser.add_argument("--buy-number", metavar="AREA_CODE", help="provision a free Vapi US number")
    parser.add_argument("--phone-number-id", default=os.getenv("VAPI_PHONE_NUMBER_ID"),
                        help="existing Vapi phone number id to attach the assistant to")
    args = parser.parse_args()

    public_url = _require("PUBLIC_BASE_URL")
    config = build_assistant_config(public_url, os.getenv("VAPI_WEBHOOK_SECRET", ""))
    if args.dry_run:
        print(json.dumps(config, indent=2))
        return

    headers = {"Authorization": f"Bearer {_require('VAPI_API_KEY')}"}
    with httpx.Client(base_url=VAPI_BASE, headers=headers, timeout=30) as client:
        assistant_id = os.getenv("VAPI_ASSISTANT_ID", "").strip()
        if not assistant_id:
            existing = _check(client.get("/assistant", params={"limit": 100}), "list assistants")
            match = next((a for a in existing if a.get("name") == ASSISTANT_NAME), None)
            assistant_id = match["id"] if match else ""

        if assistant_id:
            assistant = _check(client.patch(f"/assistant/{assistant_id}", json=config), "update assistant")
            print(f"Updated assistant {assistant['id']}")
        else:
            assistant = _check(client.post("/assistant", json=config), "create assistant")
            print(f"Created assistant {assistant['id']}")
        assistant_id = assistant["id"]

        if args.buy_number:
            number = _check(
                client.post("/phone-number", json={
                    "provider": "vapi",
                    "numberDesiredAreaCode": args.buy_number,
                    "assistantId": assistant_id,
                    "name": "Patient Intake Line",
                }),
                "provision phone number",
            )
            print(f"Provisioned {number.get('number') or '(number pending)'} id={number['id']}")
        elif args.phone_number_id:
            number = _check(
                client.patch(f"/phone-number/{args.phone_number_id}", json={"assistantId": assistant_id}),
                "attach phone number",
            )
            print(f"Attached assistant to {number.get('number')} (id={number['id']})")
        else:
            numbers = _check(client.get("/phone-number"), "list phone numbers")
            print("Phone numbers on this account:")
            for n in numbers:
                attached = " <- this assistant" if n.get("assistantId") == assistant_id else ""
                print(f"  {n.get('number')}  id={n['id']}{attached}")
            if not numbers:
                print("  (none) re-run with --buy-number <area code>")

    print(f"Webhook: {config['server']['url']}")


if __name__ == "__main__":
    main()
