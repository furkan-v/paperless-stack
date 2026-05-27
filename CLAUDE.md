# CLAUDE.md

Self-hosted **Paperless-ngx** stack with optional local AI (Ollama + paperless-gpt), wired together by a single Docker Compose file.

This repo is **configuration-only** — there is no application source code, no build step, and no test suite. All behavior comes from upstream container images. "Working in this repo" means editing `compose.yaml`, the per-service `.env` files, and the paperless-gpt prompt templates.

User-facing setup lives in `README.md`; this file is the operator/contributor map.

---

## Stack Topology

Defined entirely in `compose.yaml`. All containers share the default Compose network and resolve each other by **service name** (e.g. `http://paperless:8000`, `redis://redis:6379`).

| Service        | Image                                         | Host port | Depends on                        | Role                                          |
| -------------- | --------------------------------------------- | --------- | --------------------------------- | --------------------------------------------- |
| `paperless`    | `ghcr.io/paperless-ngx/paperless-ngx:latest`  | `8000`    | postgres, redis, gotenberg, tika  | Document management UI/API                    |
| `postgres`     | `postgres:18`                                 | —         | —                                 | Paperless database                            |
| `redis`        | `redis:8`                                     | —         | —                                 | Paperless cache + task broker                 |
| `gotenberg`    | `gotenberg/gotenberg:8.25`                    | —         | —                                 | Office → PDF conversion                       |
| `tika`         | `apache/tika:latest`                          | —         | —                                 | Text extraction from PDF/Office               |
| `ollama`       | `ollama/ollama:latest`                        | —         | —                                 | Local LLM inference                           |
| `open-webui`   | `ghcr.io/open-webui/open-webui:latest`        | `3001`    | ollama                            | Browser UI for managing/pulling Ollama models |
| `paperless-gpt`| `icereed/paperless-gpt:latest`                | `3002`    | ollama, paperless                 | LLM-driven OCR, titling, tagging, fields      |
| `dozzle`       | `amir20/dozzle:latest`                        | `8080`    | —                                 | Real-time Docker log viewer                   |

The AI services (`ollama`, `open-webui`, `paperless-gpt`) are optional — commenting them out leaves a working Paperless install.

---

## Repository Layout

```
compose.yaml                  # the only orchestration file — single source of truth
README.md                     # user-facing quick start
CLAUDE.md                     # this file
.gitignore                    # excludes runtime/state dirs + project-root .env
.env.example                  # template for the gitignored ./.env (secrets)
.env                          # *gitignored*; holds PAPERLESS_API_TOKEN and similar

<service>/.env                # per-service env file, committed (timezone + non-secret config)
paperless-gpt/prompts/*.tmpl  # Go text/template files mounted into paperless-gpt
```

Every service has its own top-level directory and committed `.env` for non-secret config. The one secret in this stack — `PAPERLESS_API_TOKEN` for paperless-gpt — is **not** committed: `compose.yaml` declares it under `environment:` as `${PAPERLESS_API_TOKEN-}`, interpolated from the gitignored project-root `./.env` (template: `.env.example`). All other paperless-gpt config still lives in `paperless-gpt/.env`.

State persists via **bind mounts** (not Docker named volumes), so all data lives inside the repo working tree — the backup story is "tar the repo, exclude `.git` and `.env`".

### Gitignored runtime paths
Per `.gitignore`: `dozzle/`, `gotenberg/`, `ollama/data`, `ollama/models`, `open-webui/data`, `paperless/{consume,data,export,media}`, `paperless-gpt/`, `postgres/data`, `redis/data`, `tika/`. **Never read, modify, or commit anything under these paths.** Treat them as opaque service state. (Note: the `.gitignore` also covers some service folders wholesale, so the data dirs themselves don't need explicit per-service ignores.)

---

## Cross-Service Config Contracts

These values are duplicated across files and must stay in sync. Changing one without the other will break startup or silently misbehave.

1. **Postgres credentials** — `paperless/.env` (`PAPERLESS_DBNAME` / `_DBUSER` / `_DBPASS`) must match `postgres/.env` (`POSTGRES_DB` / `_USER` / `_PASSWORD`). The committed defaults are `paperless`/`paperless`/`paperless` — change all six values together before production use.
2. **Paperless ↔ paperless-gpt** — `paperless-gpt/.env` sets `PAPERLESS_BASE_URL=http://paperless:8000`. `PAPERLESS_API_TOKEN` is **deliberately not in that file** — it's interpolated by `compose.yaml`'s `environment:` block from the gitignored project-root `./.env`. The token is generated in the Paperless UI (Profile → API Tokens) and is **specific to a single Paperless install** — every fresh deploy needs its own. Without it set, paperless-gpt starts but cannot reach Paperless.
3. **Ollama address** — `open-webui/.env` (`OLLAMA_BASE_URL`) and `paperless-gpt/.env` (`OLLAMA_HOST`) both target `http://ollama:11434`.
4. **LLM model names** — `paperless-gpt/.env` names the text model (`LLM_MODEL`, currently `llama3.2:3b`) and vision model (`VISION_LLM_MODEL`, currently `qwen3-vl:2b-instruct`). These models must be pulled into Ollama (`docker compose exec ollama ollama pull <name>` or via Open WebUI) before paperless-gpt can use them.
5. **Timezone** — every service's `.env` carries `TZ=Europe/Berlin`. Relocating means changing it in all nine files.

---

## paperless-gpt Prompt Templates

`paperless-gpt/prompts/*.tmpl` are **Go `text/template`** files, bind-mounted at `/app/prompts` inside the container. They control how the LLM produces each metadata field. Edits take effect on `docker compose restart paperless-gpt`.

| File                              | What it produces                       | Notable template vars                                              |
| --------------------------------- | -------------------------------------- | ------------------------------------------------------------------ |
| `ocr_prompt.tmpl`                 | Vision-LLM OCR output (markdown)       | *(none — image is passed natively)*                                |
| `title_prompt.tmpl`               | Document title                         | `.Title`, `.Content`, `.Language`                                  |
| `tag_prompt.tmpl`                 | Comma-separated tag list               | `.AvailableTags`, `.Title`, `.Content`, `.Language`                |
| `correspondent_prompt.tmpl`       | Sender/recipient name                  | `.AvailableCorrespondents`, `.BlackList`, `.Title`, `.Content`     |
| `document_type_prompt.tmpl`       | Document type                          | `.AvailableDocumentTypes`, `.Title`, `.Content`                    |
| `created_date_prompt.tmpl`        | `YYYY-MM-DD`                           | `.Content`, `.Language`, `.Today`                                  |
| `custom_field_prompt.tmpl`        | JSON array of `{field, value}`         | `.Title`, `.Content`, `.CreatedDate`, `.DocumentType`, `.CustomFieldsXML` |
| `adhoc-analysis_prompt.tmpl`      | Multi-document ad-hoc analysis output  | `range .Documents` with `.Correspondent`, `.CreatedDate`, `.CustomFields`, … |

Upstream docs for the template surface and additional vars: <https://github.com/icereed/paperless-gpt>.

---

## Conventions

- **`compose.yaml` is canonical.** Service names there become DNS names inside the network and appear in every `.env` — don't rename casually.
- **Image pinning is uneven**: `postgres:18`, `redis:8`, `gotenberg:8.25` are pinned; `paperless-ngx`, `ollama`, `open-webui`, `paperless-gpt`, `tika`, `dozzle` ride `:latest`. When pulling updates, check upstream release notes for the pinned majors and for breaking changes in the `:latest` images.
- **Bind mounts only.** Don't introduce Docker named volumes — it breaks the "tar the repo" backup model.
- **No healthchecks.** `depends_on` only orders starts, not readiness. First few seconds after `up` can have flaky inter-service calls; add `condition: service_healthy` blocks if you start defining healthchecks.
- **NVIDIA GPU passthrough was removed from compose** (commit `f2ecaef`). The env vars `NVIDIA_DRIVER_CAPABILITIES` and `NVIDIA_VISIBLE_DEVICES` remain in `ollama/.env` as hints; re-enabling GPU also requires a `deploy.resources.reservations.devices` block in `compose.yaml`.
- **`paperless-ai` was removed from this stack** (commits `4b388b9`, `cb06cf6`). The replacement is `paperless-gpt`. Don't reintroduce paperless-ai references in docs or compose.

---

## Common Operations

```bash
# Start / stop
docker compose up -d
docker compose down                              # data preserved on disk

# Update images
docker compose pull && docker compose up -d

# Logs
docker compose logs -f <service>                 # or http://localhost:8080 (Dozzle)
docker compose ps                                # status

# Pull an Ollama model
docker compose exec ollama ollama pull <model>   # or via Open WebUI

# Paperless management commands
docker compose exec paperless python3 manage.py <cmd>

# Validate compose changes
docker compose config                            # parse/schema check
```

Manual smoke test after changes: <http://localhost:8000> (Paperless), <http://localhost:3001> (Open WebUI), <http://localhost:3002> (paperless-gpt), <http://localhost:8080> (Dozzle).

---

## Gotchas

- **`paperless-gpt/.env` is dotenv `KEY=VALUE`, not YAML `KEY: VALUE`.** Earlier revisions used the YAML form, which Docker Compose's `env_file` directive silently fails to parse — env vars never reached the container. If you're copy-pasting from upstream paperless-gpt examples (which use inline YAML under `environment:`), translate to `KEY=VALUE` before adding to this file.
- **`PAPERLESS_API_TOKEN` must never be committed.** It's set in the gitignored project-root `./.env` and pulled into the container via `compose.yaml`'s `environment: PAPERLESS_API_TOKEN: ${PAPERLESS_API_TOKEN-}`. A real token (`c445b4d2…`) lived in the historical `paperless-gpt/.env` and has been rotated; if you ever see that value reappear in a diff, that's a regression.
- **Postgres mount targets the parent dir.** `./postgres/data:/var/lib/postgresql` mounts the parent of `PGDATA` (`/var/lib/postgresql/data`), so real data ends up at `./postgres/data/data/` on the host. This is intentional but surprising; preserve it on migrations.
- **Open WebUI's `depends_on: ollama` is start-order only.** Model list may briefly be empty on first load while Ollama warms up.
- **`open-webui` is not exposed to LAN by default** (port `3001` on `localhost`). Combined with the README's "use a VPN for remote access" guidance, this stack is designed for trusted networks only — don't add public ingress without adding auth in front.

---

## Out of Scope

No source code, no tests, no CI, no build pipeline. Changes are validated by:

1. `docker compose config` — schema/syntax
2. `docker compose up -d` + `docker compose ps` + Dozzle — runtime health
3. Opening each service URL — feature smoke test

Do not invent test suites, linters, or CI workflows unless explicitly asked.

---

## References

- `README.md` — user-facing quick start
- Paperless-ngx: <https://docs.paperless-ngx.com>
- paperless-gpt: <https://github.com/icereed/paperless-gpt>
- Ollama: <https://github.com/ollama/ollama>
- Open WebUI: <https://docs.openwebui.com>
- Gotenberg: <https://gotenberg.dev>
- Apache Tika: <https://tika.apache.org>
- Stack walkthrough (Tim Stewart): <https://technotim.com/posts/paperless-ngx-local-ai/>
