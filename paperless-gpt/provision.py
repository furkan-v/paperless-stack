#!/usr/bin/env python3
"""Provision Paperless tags, document types, and custom fields to match
`paperless-gpt/TAXONOMY.md`. Idempotent — safe to re-run.

Usage:
    python3 paperless-gpt/provision.py

Reads PAPERLESS_API_TOKEN from the environment first, then falls back to the
project-root .env file. Set PAPERLESS_BASE_URL to override the default
(http://localhost:8000).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# --- Taxonomy ---------------------------------------------------------------

TAGS: list[str] = [
    # Financial nature
    "invoice", "receipt", "statement", "quote",
    # Domain
    "rent", "utilities", "internet-telecom", "banking", "insurance",
    "subscription", "tax", "residency", "visa-immigration", "government",
    "legal", "employment", "payslip", "freelance-business",
    "flight", "hotel-lodging", "train-rail", "restaurant-bar", "event-ticket",
    "vehicle", "health-medical", "prescription", "education",
    "groceries", "shopping-retail", "home-services",
    # Qualifiers
    "tax-deductible", "actionable", "identification", "confidential",
    "warranty", "recurring",
]

DOCUMENT_TYPES: list[str] = [
    "Invoice", "Receipt", "Statement", "Contract", "Letter", "Form",
    "Notice", "Tax Document", "Payslip", "Certificate", "Identification",
    "Booking", "Ticket", "Medical Record", "Warranty", "Quote", "Report",
]

# (name, paperless data_type) — types: monetary, date, boolean, string, integer, float, url, documentlink
CUSTOM_FIELDS: list[tuple[str, str]] = [
    ("Total Amount", "monetary"),
    ("Tax / VAT Amount", "monetary"),
    ("Amount Due", "monetary"),
    ("Due Date", "date"),
    ("Service Period Start", "date"),
    ("Service Period End", "date"),
    ("Event / Reservation Date", "date"),
    ("Document Number", "string"),
    ("Customer Number", "string"),
    ("Reference", "string"),
    ("Tax Deductible", "boolean"),
    ("Residency-Related", "boolean"),
    ("Recurring", "boolean"),
    ("Action Required", "boolean"),
    ("Brief Summary", "string"),
]

# --- Config -----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_token() -> str:
    token = os.environ.get("PAPERLESS_API_TOKEN")
    if token:
        return token.strip()
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        sys.exit(
            f"ERROR: PAPERLESS_API_TOKEN not in env and {env_path} does not exist.\n"
            "Copy .env.example to .env and set PAPERLESS_API_TOKEN."
        )
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key.strip() == "PAPERLESS_API_TOKEN":
            return value.strip().strip('"\'')
    sys.exit(f"ERROR: PAPERLESS_API_TOKEN not found in {env_path}.")


BASE_URL = os.environ.get("PAPERLESS_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = load_token()
HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# --- API helpers ------------------------------------------------------------


def api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            payload = resp.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        sys.exit(f"ERROR: {method} {path} -> {e.code} {e.reason}\n{detail}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: cannot reach {url} ({e.reason}). Is Paperless running?")


def list_all(path: str) -> list[dict]:
    items: list[dict] = []
    url = path
    while url:
        page = api("GET", url)
        items.extend(page.get("results", []))
        next_url = page.get("next")
        if not next_url:
            break
        url = next_url.removeprefix(BASE_URL)
    return items


def ensure(label: str, path: str, existing: set[str], desired: list, payload_fn) -> None:
    print(f"{label}:")
    created = skipped = 0
    for item in desired:
        name = item if isinstance(item, str) else item[0]
        if name in existing:
            skipped += 1
            continue
        api("POST", path, payload_fn(item))
        created += 1
        print(f"  + {name}")
    print(f"  ({created} created, {skipped} already present)")


# --- Main -------------------------------------------------------------------


def main() -> None:
    print(f"Provisioning Paperless taxonomy on {BASE_URL}\n")

    existing_tags = {t["name"] for t in list_all("/api/tags/")}
    ensure("Tags", "/api/tags/", existing_tags, TAGS, lambda name: {"name": name})

    existing_types = {d["name"] for d in list_all("/api/document_types/")}
    ensure(
        "Document types", "/api/document_types/", existing_types, DOCUMENT_TYPES,
        lambda name: {"name": name},
    )

    existing_fields = {f["name"] for f in list_all("/api/custom_fields/")}
    ensure(
        "Custom fields", "/api/custom_fields/", existing_fields, CUSTOM_FIELDS,
        lambda item: {"name": item[0], "data_type": item[1]},
    )

    print("\nDone. paperless-gpt reads tags/types/fields live; no restart required.")


if __name__ == "__main__":
    main()
