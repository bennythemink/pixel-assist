# Pixel Assist

White-label AI chat product by Pixel Agency. Each instance runs on its own DigitalOcean Droplet and provides an embeddable chat widget to client websites.

## Architecture

```
Client website (external)
        │
        ▼
   Cloudflare (DNS + edge proxy)
        │
        ▼
   Caddy (TLS termination + routing + CORS)
        │
        ├──  /api/embed/*/stream-chat  ──▶  PII Proxy (scrubs personal data)  ──▶  AnythingLLM
        │
        └──  everything else  ──▶  AnythingLLM (direct)
```

All services run as Docker containers on a shared network called `caddy-net`. Client websites are hosted externally — the Droplet only runs the AI chat backend and its middleware.

## Folder Structure

```
caddy/                  Caddy reverse proxy
  Caddyfile             Site blocks per subdomain
  docker-compose.yml
  certs/                Cloudflare origin certs (not committed)

middleware/             PII-scrubbing middleware
  docker-compose.yml
  caddyfile-llm1-block.txt
  pii-proxy/            FastAPI application
    Dockerfile
    pyproject.toml
    app/
      main.py
      proxy.py
      scrubber.py
      session_store.py
      config.py

anythingllm/            AnythingLLM RAG chat
  docker-compose.yml

tutorial.html           Interactive Droplet setup guide
```

## Services

### Caddy (`caddy/`)

Reverse proxy handling TLS termination, routing, and CORS.

- **Image:** `caddy:2-alpine`
- **Ports:** 80, 443 (only service exposed to the host)
- **TLS:** Uses Cloudflare origin certificates from `caddy/certs/` (`auto_https off`)
- **CORS:** All CORS headers are set in Caddy — not in the FastAPI app — to avoid duplicate `Access-Control-Allow-Origin` headers
- **Routing:** Chat stream requests (`/api/embed/*/stream-chat`) route to the PII proxy; everything else goes directly to AnythingLLM
- **SSE:** `flush_interval -1` on the PII proxy route enables Server-Sent Events streaming
- **Data:** Persisted to DigitalOcean block storage

### PII Proxy (`middleware/`)

FastAPI proxy that scrubs personally identifiable information from user messages before they reach the LLM.

- **Stack:** Python 3.11, FastAPI, uvicorn, httpx, packaged with `uv`
- **Detection:** Microsoft Presidio + spaCy (`en_core_web_lg`)
- **Intercepts:** Only `POST /api/embed/{embed_id}/stream-chat`

**Detected PII entities:**

| Entity          | Source                                                    |
| --------------- | --------------------------------------------------------- |
| `PERSON`        | Presidio built-in (spaCy NER)                             |
| `EMAIL_ADDRESS` | Presidio built-in                                         |
| `AU_PHONE`      | Custom recognizer — mobiles, landlines, +61 formats       |
| `AU_ABN`        | Custom recognizer — Australian Business Number            |
| `AU_ACN`        | Custom recognizer — Australian Company Number             |
| `AU_MEDICARE`   | Custom recognizer — Medicare card numbers                 |
| `AU_ADDRESS`    | Custom recognizer — street addresses (unit, slash, basic) |
| `AU_DOB`        | Custom recognizer — dates of birth                        |

> `LOCATION` is deliberately excluded so suburb names pass through; full street addresses are caught by `AU_ADDRESS` regex patterns instead.

**Key behaviours:**

- Session-consistent pseudonyms — the same name in the same session always maps to the same placeholder (e.g. `[PERSON_1]`)
- Fail-open — if Presidio errors, the original message is forwarded unmodified
- Strips CORS headers from upstream AnythingLLM responses (Caddy owns CORS)

**Environment variables:**

| Variable                | Default                   | Description                           |
| ----------------------- | ------------------------- | ------------------------------------- |
| `ANYTHINGLLM_BASE_URL`  | `http://anythingllm:3001` | Upstream AnythingLLM URL              |
| `LOG_LEVEL`             | `info`                    | Logging level                         |
| `SESSION_TTL_HOURS`     | `24`                      | Session pseudonym expiry              |
| `SCRUB_SCORE_THRESHOLD` | `0.35`                    | Minimum confidence to scrub an entity |

### AnythingLLM (`anythingllm/`)

RAG-powered chat engine providing the embeddable widget.

- **Image:** `mintplexlabs/anythingllm`
- **Port:** 3001 (internal to `caddy-net`, not published)
- **Storage:** Persisted to DigitalOcean block storage
- **Requires:** `cap_add: SYS_ADMIN`
- The embed widget is configured via AnythingLLM's admin UI, which generates a `<script>` tag for the client website

## Networking

- All containers join the external Docker network `caddy-net`
- Only Caddy publishes ports to the host (80, 443)
- Containers reference each other by container name (e.g. `anythingllm`, `pii-proxy`)

## TLS / Cloudflare

- Cloudflare manages DNS and acts as the edge proxy
- Wildcard origin certificates go in `caddy/certs/` as `origin.pem` and `origin-key.pem`
- Cloudflare SSL mode: **Full** (not "Full (Strict)" — origin certs are Cloudflare-issued, not from a public CA)

## Deployment

Detailed steps are in `tutorial.html`. Quick summary:

1. Create a DigitalOcean Droplet and attach block storage
2. Install Docker and create the `caddy-net` network:
   ```bash
   docker network create caddy-net
   ```
3. Copy this repo to the server (e.g. `/srv/`)
4. Place Cloudflare origin certificates in `caddy/certs/`
5. Update the Caddyfile with the client's subdomain
6. Update volume paths in each `docker-compose.yml` to match the Droplet's block storage
7. Start all services:
   ```bash
   cd caddy && docker compose up -d --build && cd ..
   cd anythingllm && docker compose up -d --build && cd ..
   cd middleware && docker compose up -d --build && cd ..
   ```
8. Configure AnythingLLM via its web UI — create a workspace, set up the embed
9. Add the generated `<script>` tag to the client's website

## Gotchas

- **CORS duplication** — CORS headers must only be set in Caddy. Do not add `CORSMiddleware` to FastAPI or the browser will reject responses with duplicate `Access-Control-Allow-Origin` headers. The PII proxy strips any CORS headers from upstream responses.
- **SSE streaming** — `flush_interval -1` is required on Caddy's `reverse_proxy` block for the PII proxy route, otherwise streaming breaks with "aborting with incomplete response".
- **First build is slow** — The spaCy `en_core_web_lg` model is ~560 MB. It's installed as a separate Docker layer so subsequent builds use the cache.
- **SYS_ADMIN capability** — The AnythingLLM container requires `cap_add: SYS_ADMIN`.
