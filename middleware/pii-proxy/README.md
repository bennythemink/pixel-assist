# PII Proxy — Phase 2

A FastAPI reverse-proxy that sits between Caddy and AnythingLLM, scrubbing
personally identifiable information (PII) from user messages before they reach
the LLM workspace.

## Architecture

```
Browser → Caddy (TLS) → pii-proxy :8000 → AnythingLLM :3001
```

Caddy routes `/api/embed/*/stream-chat` to pii-proxy. All other AnythingLLM
traffic goes direct.

## Build & Run

```bash
cd Droplet/middleware
docker compose up -d --build
```

Health check:

```bash
curl http://localhost:8000/health
# {"status":"ok","phase":2,"presidio":true,"spacy_model":"en_core_web_lg","active_sessions":0}
```

## Environment Variables

| Variable                | Default                    | Description                                              |
| ----------------------- | -------------------------- | -------------------------------------------------------- |
| `ANYTHINGLLM_BASE_URL`  | `http://anythingllm1:3001` | Upstream AnythingLLM URL                                 |
| `LOG_LEVEL`             | `info`                     | Python log level                                         |
| `SESSION_TTL_HOURS`     | `24`                       | Hours before idle session pseudonym maps expire          |
| `SCRUB_SCORE_THRESHOLD` | `0.35`                     | Minimum Presidio confidence score to trigger replacement |

## Custom Australian Recognizers

| Entity        | Pattern                                                                                                | Base Score | Context Words                                         |
| ------------- | ------------------------------------------------------------------------------------------------------ | ---------- | ----------------------------------------------------- |
| `AU_PHONE`    | Mobile: `04xx xxx xxx`, `04xxxxxxxx`, `+614...`. Landline: `(0x) xxxx xxxx`, `0x xxxx xxxx`, `+61x...` | 0.6–0.9    | phone, mobile, cell, contact, call, ring, number, tel |
| `AU_ABN`      | `xx xxx xxx xxx` (11 digits)                                                                           | 0.3        | ABN, business number                                  |
| `AU_ACN`      | `xxx xxx xxx` (9 digits)                                                                               | 0.2        | ACN, company number                                   |
| `AU_MEDICARE` | `[2-6]xxx xxxxx x[x]` (10–11 digits, first digit 2–6)                                                  | 0.3        | Medicare, card number                                 |
| `AU_ADDRESS`  | `42 Smith Street`, `Unit 3, 15 George St`, `3/15 George St`, optional suburb/state/postcode            | 0.7–0.85   | address, live, located, reside, property, renovation  |
| `AU_DOB`      | `DD/MM/YYYY`, `DD Month YYYY`, `Month DD, YYYY`                                                        | 0.1        | born, dob, date of birth, birthday                    |

Built-in Presidio entities also active: `PERSON`, `EMAIL_ADDRESS`.

`LOCATION` is **excluded** so suburb names (e.g. "Ballarat") pass through
un-scrubbed.

## Session Pseudonyms

Each chat session gets consistent placeholders. If a user mentions "Sarah" twice
in the same session, both occurrences map to `[PERSON_1]`. A different person in
the same session becomes `[PERSON_2]`.

Sessions expire after `SESSION_TTL_HOURS` of inactivity (default 24h). A
background task cleans up expired sessions every 5 minutes.

## Testing

Send messages containing PII through the chat widget and verify scrubbing:

| Input                                        | Expected                              |
| -------------------------------------------- | ------------------------------------- |
| Hi, my name is Sarah Johnson                 | `[PERSON_1]` replaces "Sarah Johnson" |
| Email me at sarah@example.com                | `[EMAIL_1]` replaces the email        |
| Call me on 0412 345 678                      | `[PHONE_1]` replaces the number       |
| I live at 42 Smith Street, Ballarat VIC 3350 | `[ADDRESS_1]` replaces the address    |
| I'm in Ballarat                              | Not scrubbed (LOCATION excluded)      |
| My birthday is 15/03/1985                    | `[DOB_1]` replaces the date           |

## Fail-Open Policy

If Presidio analysis raises an exception, the original message is forwarded
un-modified. This ensures the chat remains functional even if the scrubbing
engine encounters an unexpected input.
