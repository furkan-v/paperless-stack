#!/usr/bin/env python3
"""Translation service for Paperless documents.

Polls Paperless every POLL_INTERVAL seconds for documents that paperless-gpt
has already finished processing (no `paperless-gpt-auto` or
`paperless-gpt-ocr-auto` tag) and whose `Is Translated` custom field is not
yet `true`. For each candidate it detects the source language with
langdetect, calls Ollama with the configured translation model, appends the
English translation below the original content, and flips `Is Translated`
to `true` so the doc isn't reprocessed.

All inference is local (Ollama + langdetect). No external API calls.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0  # deterministic langdetect results

# --- Config -----------------------------------------------------------------

PAPERLESS_BASE_URL = os.environ.get("PAPERLESS_BASE_URL", "http://paperless:8000").rstrip("/")
PAPERLESS_API_TOKEN = os.environ.get("PAPERLESS_API_TOKEN", "").strip()
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434").rstrip("/")
TRANSLATE_MODEL = os.environ.get("TRANSLATE_MODEL", "translategemma:4b")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))
MIN_CONTENT_LENGTH = int(os.environ.get("MIN_CONTENT_LENGTH", "30"))
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", "12000"))

TARGET_LANGUAGE_CODE = "en"
TARGET_LANGUAGE_NAME = "English"
TRANSLATED_FIELD_NAME = "Is Translated"
STILL_PROCESSING_TAG_NAMES = {"paperless-gpt-auto", "paperless-gpt-ocr-auto"}
TRANSLATION_MARKER = "--- English Translation ---"
PROMPT_PATH = Path("/app/prompts/translate.tmpl")

# ISO 639-1 codes whose detected language should NOT be translated — the doc
# is still marked `Is Translated = true` so the polling loop stops seeing it.
# Configurable via env (comma-separated, e.g. "en,tr,fr"). TARGET_LANGUAGE_CODE
# is force-added below so an empty value can never trigger English -> English.
SKIP_LANGUAGES: set[str] = {
    code.strip().lower()
    for code in os.environ.get("SKIP_LANGUAGES", "en,tr").split(",")
    if code.strip()
}
SKIP_LANGUAGES.add(TARGET_LANGUAGE_CODE)

# ISO 639-1 codes → full language names, used to fill the translategemma prompt
# template (see https://ollama.com/library/translategemma — it expects both the
# full name and the ISO code in each placeholder).
LANG_CODE_TO_NAME: dict[str, str] = {
    "de": "German", "en": "English", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "tr": "Turkish",
    "ru": "Russian", "pl": "Polish", "cs": "Czech", "sk": "Slovak",
    "sv": "Swedish", "da": "Danish", "no": "Norwegian", "fi": "Finnish",
    "hu": "Hungarian", "ro": "Romanian", "bg": "Bulgarian", "el": "Greek",
    "uk": "Ukrainian", "hr": "Croatian", "sl": "Slovenian", "et": "Estonian",
    "lv": "Latvian", "lt": "Lithuanian", "ar": "Arabic", "fa": "Persian",
    "he": "Hebrew", "ja": "Japanese", "ko": "Korean", "vi": "Vietnamese",
    "th": "Thai", "id": "Indonesian", "hi": "Hindi",
}

PAPERLESS_HEADERS = {
    "Authorization": f"Token {PAPERLESS_API_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# --- HTTP helpers -----------------------------------------------------------


def paperless(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{PAPERLESS_BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=PAPERLESS_HEADERS, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = resp.read()
        return json.loads(payload) if payload else {}


def ollama_generate(prompt: str) -> str:
    body = json.dumps({
        "model": TRANSLATE_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # Translation of a long page can take a minute or two on small hardware.
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read()).get("response", "")


def list_all_paginated(path: str) -> list[dict]:
    items: list[dict] = []
    url = path
    while url:
        page = paperless("GET", url)
        items.extend(page.get("results", []))
        next_url = page.get("next")
        if not next_url:
            break
        url = next_url.removeprefix(PAPERLESS_BASE_URL)
    return items


# --- Paperless lookups ------------------------------------------------------


def get_tag_id_map() -> dict[str, int]:
    return {t["name"]: t["id"] for t in list_all_paginated("/api/tags/?page_size=200")}


def get_custom_field_id(name: str) -> int | None:
    for f in list_all_paginated("/api/custom_fields/"):
        if f["name"] == name:
            return f["id"]
    return None


def find_candidates(still_processing_tag_ids: set[int], translated_field_id: int) -> list[dict]:
    """Documents not still being processed by paperless-gpt and not yet translated."""
    if still_processing_tag_ids:
        exclude_param = ",".join(str(i) for i in still_processing_tag_ids)
        query = f"/api/documents/?tags__id__none={exclude_param}&page_size=100"
    else:
        query = "/api/documents/?page_size=100"
    all_done = list_all_paginated(query)

    result: list[dict] = []
    for doc in all_done:
        if _is_marked_translated(doc, translated_field_id):
            continue
        result.append(doc)
    return result


def _is_marked_translated(doc: dict, translated_field_id: int) -> bool:
    for cf in doc.get("custom_fields", []):
        if cf.get("field") == translated_field_id and cf.get("value") is True:
            return True
    return False


# --- Translation ------------------------------------------------------------


def detect_language(content: str) -> str:
    try:
        return detect(content)
    except LangDetectException:
        return "unknown"


def load_prompt_template() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    # Hard fallback if the bind-mount or COPY is broken. Mirrors translategemma's
    # expected format (https://ollama.com/library/translategemma) so the model
    # stays in-distribution even if the template file disappears.
    return (
        "You are a professional {{source_lang_name}} ({{source_lang_code}}) to "
        "{{target_lang_name}} ({{target_lang_code}}) translator. Your goal is to "
        "accurately convey the meaning and nuances of the original "
        "{{source_lang_name}} text while adhering to {{target_lang_name}} "
        "grammar, vocabulary, and cultural sensitivities. Produce only the "
        "{{target_lang_name}} translation, without any additional explanations "
        "or commentary. Please translate the following {{source_lang_name}} "
        "text into {{target_lang_name}}:\n\n\n{{content}}\n"
    )


def lang_metadata(detected_code: str) -> tuple[str, str]:
    """Map a langdetect code to (full language name, ISO code) for the prompt.

    Handles translategemma's special-cased Chinese variants and falls back to
    using the code itself as the name for any language not in LANG_CODE_TO_NAME.
    """
    if detected_code == "zh-cn":
        return ("Chinese (Simplified)", "zh-Hans")
    if detected_code == "zh-tw":
        return ("Chinese (Traditional)", "zh-Hant")
    name = LANG_CODE_TO_NAME.get(detected_code)
    if name is None:
        return (detected_code.upper(), detected_code)
    return (name, detected_code)


# Common preambles some models prepend despite instructions — strip them.
_PREAMBLE_PREFIXES = (
    "translation:",
    "english:",
    "english translation:",
    "here is the translation:",
    "here's the translation:",
    "translated text:",
)


def _strip_preamble(text: str) -> str:
    stripped = text.lstrip()
    lower = stripped.lower()
    for prefix in _PREAMBLE_PREFIXES:
        if lower.startswith(prefix):
            return stripped[len(prefix):].lstrip()
    return text.strip()


def translate(content: str, source_lang_code: str) -> str:
    source_name, source_code = lang_metadata(source_lang_code)
    prompt = (
        load_prompt_template()
        .replace("{{source_lang_name}}", source_name)
        .replace("{{source_lang_code}}", source_code)
        .replace("{{target_lang_name}}", TARGET_LANGUAGE_NAME)
        .replace("{{target_lang_code}}", TARGET_LANGUAGE_CODE)
        .replace("{{content}}", content)
    )
    return _strip_preamble(ollama_generate(prompt))


# --- Mutation ---------------------------------------------------------------


def patch_document(doc: dict, new_content: str | None, translated_field_id: int) -> None:
    """PATCH the document's content (if changed) and mark Is Translated = true.

    Preserves any other custom-field assignments already present on the doc.
    """
    existing_fields = doc.get("custom_fields", []) or []
    merged: list[dict] = []
    found = False
    for cf in existing_fields:
        if cf.get("field") == translated_field_id:
            merged.append({"field": translated_field_id, "value": True})
            found = True
        else:
            merged.append({"field": cf["field"], "value": cf.get("value")})
    if not found:
        merged.append({"field": translated_field_id, "value": True})

    payload: dict = {"custom_fields": merged}
    if new_content is not None:
        payload["content"] = new_content

    paperless("PATCH", f"/api/documents/{doc['id']}/", payload)


# --- Per-document handling --------------------------------------------------


def process_document(doc: dict, translated_field_id: int) -> str:
    doc_id = doc["id"]
    content = (doc.get("content") or "")

    if len(content) < MIN_CONTENT_LENGTH:
        # Mark so we don't re-check on every tick.
        patch_document(doc, None, translated_field_id)
        return "skipped:too_short"

    if TRANSLATION_MARKER in content:
        # A previous run already appended a translation but didn't flip the flag.
        patch_document(doc, None, translated_field_id)
        return "skipped:already_appended"

    lang = detect_language(content)
    if lang in SKIP_LANGUAGES:
        patch_document(doc, None, translated_field_id)
        return f"skipped:{lang}"
    if lang == "unknown":
        # Don't mark — try again next poll in case content grows.
        return "skipped:lang_unknown"

    to_translate = content[:MAX_CONTENT_LENGTH]
    truncated = len(content) > MAX_CONTENT_LENGTH

    try:
        translation = translate(to_translate, lang)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  doc {doc_id}: ollama HTTP {e.code}: {body[:200]}", flush=True)
        return "failed:ollama"
    except urllib.error.URLError as e:
        print(f"  doc {doc_id}: ollama unreachable: {e.reason}", flush=True)
        return "failed:ollama"

    if not translation.strip():
        return "failed:empty"

    suffix = (
        f"\n\n(Note: original was truncated to {MAX_CONTENT_LENGTH} characters before translation.)"
        if truncated
        else ""
    )
    new_content = f"{content}\n\n{TRANSLATION_MARKER}\n\n{translation}{suffix}"
    patch_document(doc, new_content, translated_field_id)
    return f"translated:{lang}"


# --- Main loop --------------------------------------------------------------


def tick() -> None:
    tag_map = get_tag_id_map()
    still_processing_tag_ids = {
        tag_map[name] for name in STILL_PROCESSING_TAG_NAMES if name in tag_map
    }

    translated_field_id = get_custom_field_id(TRANSLATED_FIELD_NAME)
    if translated_field_id is None:
        print(
            f"WARN: custom field {TRANSLATED_FIELD_NAME!r} not in Paperless yet — "
            f"run `python3 paperless-gpt/provision.py` from the host. Skipping tick.",
            flush=True,
        )
        return

    candidates = find_candidates(still_processing_tag_ids, translated_field_id)
    if not candidates:
        return

    print(f"poll: {len(candidates)} candidate doc(s)", flush=True)
    for doc in candidates:
        status = process_document(doc, translated_field_id)
        print(f"  doc {doc['id']} ({doc.get('title')!r}): {status}", flush=True)


def main() -> None:
    if not PAPERLESS_API_TOKEN:
        sys.exit("ERROR: PAPERLESS_API_TOKEN is empty. Set it in the project-root .env.")

    print(
        f"translator: starting model={TRANSLATE_MODEL} interval={POLL_INTERVAL}s "
        f"min={MIN_CONTENT_LENGTH} max={MAX_CONTENT_LENGTH} "
        f"skip={','.join(sorted(SKIP_LANGUAGES))}",
        flush=True,
    )
    print(f"  paperless: {PAPERLESS_BASE_URL}", flush=True)
    print(f"  ollama:    {OLLAMA_HOST}", flush=True)

    while True:
        try:
            tick()
        except urllib.error.URLError as e:
            print(f"poll: paperless unreachable: {e.reason}", flush=True)
        except Exception as e:
            print(f"poll error: {e!r}", flush=True)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
