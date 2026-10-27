# Voice AI Patient Registration Agent

Call a U.S. phone number and talk to **Ava**, an AI intake coordinator who registers you as a new patient. She collects the standard demographic dataset by talking with you, checks each field, reads it all back, saves it to Postgres, and can book your first appointment. Call again and she recognizes your phone number and offers to update your record instead.

## Live demo

| | |
|---|---|
| **Phone number** | **+1 (213) 727-7174** |
| **API base URL** | https://ai-voice-agent-taupe.vercel.app |
| **Dashboard** | https://ai-voice-agent-taupe.vercel.app/dashboard |
| **API docs (OpenAPI)** | https://ai-voice-agent-taupe.vercel.app/docs |
| **Credentials** | None needed. All `/patients` endpoints are open for testing. `/vapi/webhook` only accepts requests carrying the shared secret Vapi sends. |

Seed data: two fictional patients, Jane Doe `(212) 555-0101` and Carlos Rivera `(305) 555-0123`. Call and give Jane's number to try the returning-patient flow (her DOB is 03/14/1985).

---

## Architecture

```
          ┌──────────────┐  PSTN   ┌─────────────────────────────────────────┐
 Caller ──┤ Phone number ├────────►│ Vapi (managed)                          │
          └──────────────┘         │  Deepgram STT → GPT-4o → ElevenLabs TTS │
                                   │  system prompt + tool schemas (ours)    │
                                   └───────────────┬─────────────────────────┘
                                                   │ HTTPS webhook (x-webhook-secret)
                                                   │ tool-calls / status-update / end-of-call-report
┌──────────────────────────────────────────────────▼──────────────────────────┐
│ FastAPI service (this repo), one deployable                                 │
│                                                                             │
│  app/voice/      webhook.py → tools.py ─┐      app/api/  /patients, /calls  │
│  (telephony/LLM glue, prompt)           │      (REST, JSON envelope)        │
│                                         ▼              │                    │
│                       app/services/  (business logic, shared) ◄─┘           │
│                       app/validation.py (one rulebook for API + agent)      │
│                                         ▼                                   │
│                       app/models.py  SQLAlchemy ─► PostgreSQL (SQLite local)│
│                                                                             │
│  /dashboard (static HTML reading the REST API)                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Separation of concerns**

| Layer | Location | Responsibility |
|---|---|---|
| Telephony, STT, TTS, turn-taking | Vapi (managed) | Phone number, audio, barge-in, endpointing |
| Conversation design | `app/voice/prompt.py`, `app/voice/assistant.py` | System prompt, voice/model config, as code |
| Agent actions | `app/voice/tools.py` | Tool schemas the LLM sees and their handlers |
| Webhook transport | `app/voice/webhook.py` | Auth, parse Vapi messages, log, persist transcripts |
| REST API | `app/api/` | HTTP ↔ service translation, envelope, status codes |
| Business logic | `app/services/` | Patient CRUD, soft delete, call logs, appointments |
| Validation | `app/validation.py` | Normalizers used by **both** the API schemas and the agent |
| Persistence | `app/models.py`, `app/db.py` | Schema, constraints, indexes |

The voice agent does **not** write to the DB itself. It calls the same service functions as `POST /patients`/`PUT /patients/:id`, so phone and API data go through identical validation. The spec allows calling the REST API or "the same service layer"; I used the service layer to skip a pointless HTTP hop inside one process.

### A call, end to end

1. Vapi answers and speaks the first message. The caller talks, Deepgram transcribes, and GPT-4o decides what to say or which tool to call.
2. Once it has the phone number, the agent calls `lookup_patient_by_phone`. If the number matches a record, it says "It looks like we already have a record for Jane Doe. Would you like to update your information instead?" and checks the caller's DOB before changing anything.
3. After the required fields (plus any optional fields the caller opts into), it calls `validate_patient_info`. Server-side errors come back as plain-English messages per field, and the agent re-asks only for those fields.
4. It reads everything back in short groups and waits for an explicit confirmation before calling `save_patient`.
5. If the save works, it says "You're all set, Jane!" and offers to book an appointment (`get_appointment_slots` / `book_appointment`), then says goodbye and calls `endCall`.
6. Vapi sends `end-of-call-report`, and the transcript and summary are stored in `call_logs`, linked to the patient.

## Tech stack and why

| Choice | Why |
|---|---|
| **Vapi** | The spec recommends it. It handles the PSTN number, STT/TTS, barge-in and endpointing, which frees the 3 hours for the prompt, tools and data layer. The assistant is defined in code (`scripts/setup_vapi.py`), not by clicking around the Vapi dashboard. |
| **GPT-4o via Vapi** | Reliable tool calling and low latency on Vapi's hosted path, with no extra API key. Swap it with `VAPI_MODEL_PROVIDER`/`VAPI_MODEL`, for example to an Anthropic Claude model. |
| **Deepgram nova-3 `multi` + ElevenLabs turbo v2.5** | Both handle English and Spanish, so the "Hablo español" bonus works without a second assistant. |
| **FastAPI + Pydantic v2** | Typed request validation, automatic OpenAPI docs at `/docs`, and a small amount of code. |
| **SQLAlchemy 2 + PostgreSQL** | Real constraints and types in production. The same models run on SQLite for zero-setup local development and tests, and the test suite passes on both. |
| **Vercel + Neon Postgres** | Free, no card. The app runs as one serverless function; cold starts are about 1–2 s, well under Vapi's 20 s tool timeout, and the instance never sleeps for minutes the way free container hosts do. Neon is attached through Vercel's Storage tab. A Dockerfile is also included for any container host (Railway, Render, Fly). |

## Data model

`patients` follows the spec exactly, plus `deleted_at` for soft delete.

- `patient_id` UUID PK; `created_at`/`updated_at` are timezone-aware UTC timestamps.
- NOT NULL on every required field; `preferred_language` defaults to `English`.
- CHECK constraints: name and city lengths, `sex IN ('Male','Female','Other','Decline to Answer')`, phone length = 10, state length = 2, ZIP length 5 or 10.
- Indexes on `phone_number` (returning-caller lookup), `last_name` and `date_of_birth` (the API filters).
- Phone numbers are stored as 10 bare digits. DOB is a real `DATE` and is returned as `MM/DD/YYYY`.
- `phone_number` is **not unique**, on purpose: family members often share a number. Duplicate handling happens in the conversation instead.

There are also two supporting tables. `call_logs` holds the transcript, summary, ended reason, the payload the agent submitted, and a FK to the patient. `appointments` has a unique `(provider_name, starts_at)` so a slot can't be double-booked.

Rules that are awkward to express in portable SQL (name regex, valid state codes, DOB not in the future and not more than 130 years ago, NANP phone rules, email format) live in `app/validation.py`. Both the API and the agent use them.

## REST API

All responses use the envelope `{"data": ..., "error": null}`. Errors look like `{"data": null, "error": {"code", "message", "details": {field: message}}}`.

| Method | Path | Notes |
|---|---|---|
| GET | `/patients` | Filters: `?last_name=` (case-insensitive), `?date_of_birth=` (MM/DD/YYYY or ISO), `?phone_number=` (any format) |
| GET | `/patients/{id}` | 400 for a malformed UUID, 404 for an unknown or deleted patient |
| POST | `/patients` | 201 with the created record; 422 with per-field details; unknown fields rejected |
| PUT | `/patients/{id}` | Partial update; required fields can be changed but not set to null |
| DELETE | `/patients/{id}` | Soft delete (sets `deleted_at`); the record then disappears from GET/list |
| GET | `/patients/{id}/calls` | Call transcripts linked to the patient (bonus) |
| GET | `/patients/{id}/appointments` | Booked appointments (bonus) |
| GET | `/calls` | Recent calls, including ones that dropped before saving |
| GET | `/health` | Liveness and DB check |
| POST | `/vapi/webhook` | Vapi only; requires the `x-webhook-secret` header |

Status codes: 200, 201, 400 (malformed JSON or ID), 401, 404, 409 (slot taken), 422 (validation), 500 (same envelope, no stack traces).

```bash
BASE=https://ai-voice-agent-taupe.vercel.app
curl -s "$BASE/patients?last_name=doe"
curl -s -X POST "$BASE/patients" -H 'content-type: application/json' -d '{
  "first_name":"Ana","last_name":"Lopez","date_of_birth":"07/04/1990","sex":"Female",
  "phone_number":"(512) 555-0142","address_line_1":"9 Elm St","city":"Austin","state":"TX","zip_code":"78701"}'
curl -s -X PUT "$BASE/patients/<id>" -H 'content-type: application/json' -d '{"city":"Dallas"}'
curl -s -X DELETE "$BASE/patients/<id>"
```

## Prompt engineering

The full system prompt is in [`app/voice/prompt.py`](app/voice/prompt.py), with a module docstring explaining each design decision. Highlights:

- **Written for voice.** No markdown, one question per turn, varied acknowledgements, and set spoken formats ("March fifth, nineteen ninety"; phone numbers digit by digit in groups).
- **Checklist, not script.** Callers can give fields in any order or several at once, and the agent never re-asks for something it already has.
- **Corrections.** "Actually it's D-A-V-I-S" replaces only that field. The agent asks callers to spell last names because STT gets names wrong most often.
- **Two layers of validation.** The LLM catches obvious problems right away (today's date is injected through Vapi's Liquid `{{"now"}}` template so it can reject future DOBs). The server is authoritative, and its error strings are written so the agent can say them aloud.
- **Never claim success without a tool result.** If the DB write fails, the agent apologizes, retries once, then tells the caller honestly that nothing was saved. It never goes silent and never says "you're all set" unless the save succeeded.
- **Start over / hang up.** "Let's start over" clears everything collected. A caller who leaves early is told nothing was saved.
- **Verify identity before updates.** A matching phone number isn't enough. The agent checks DOB before editing and never reveals the record if the DOB doesn't match.
- **Turn-taking tuned in config** (`app/voice/assistant.py`): `startSpeakingPlan.waitSeconds=0.8` so the agent doesn't cut people off mid-phone-number, and `stopSpeakingPlan.numWords=2` so "uh-huh" doesn't interrupt it but a real interruption does.

## Edge cases and resilience

| Scenario | Behavior |
|---|---|
| Invalid DOB / 3-digit phone / bad state | The agent re-asks for that field with a reason; the server returns per-field errors (and the API returns 422) |
| Caller corrects a field | Only that field changes; confirmed in the read-back |
| Caller wants to start over | Collected data is discarded and the flow restarts |
| Call drops mid-registration | Nothing partial is saved (by design: unconfirmed data isn't trustworthy). The `end-of-call-report` still stores the transcript and ended reason, so the call shows as "Not saved" on the dashboard. |
| DB write fails | The tool returns `system_error`; the agent apologizes, retries once, then says honestly that nothing was saved. Tested in `test_db_failure_is_reported_to_agent_not_raised`. |
| Any unexpected exception in a tool | Caught in `run_tool`, logged with the call ID, and turned into a spoken apology instead of silence |
| Webhook from someone other than Vapi | 401 (shared-secret header, constant-time compare) |
| Returning caller | Detected by phone; update flow after DOB check; family members on a shared phone can still register |
| Caller speaks Spanish | The agent switches to Spanish and sets `preferred_language=Spanish` |

## Observability

JSON-lines logs on stdout, each tagged with the Vapi `call_id`: every tool call with its arguments, every tool result, the final `save_patient` payload, and the end-of-call summary and reason. The submitted payload is also stored in `call_logs.collected_payload`. To follow one call, `grep <call_id>` in the Vercel project's **Logs** tab.

## Running locally

```bash
uv venv && uv pip install -r requirements-dev.txt     # or: python -m venv .venv && pip install -r requirements-dev.txt
cp .env.example .env                                   # then edit; delete DATABASE_URL to use SQLite
.venv/bin/uvicorn app.main:app --reload                # http://localhost:8000/dashboard
.venv/bin/pytest -q                                    # 52 tests (API, validation, webhook)
TEST_DATABASE_URL=postgresql://... .venv/bin/pytest -q # same suite against Postgres
```

To talk to the agent locally, expose the server with `ngrok http 8000`, set `PUBLIC_BASE_URL` to the ngrok URL, and run `python scripts/setup_vapi.py`.

## Deployment (Vercel + Neon + Vapi)

1. In Vercel: **Add New → Project → Import** this GitHub repo (no build settings needed; `vercel.json` routes every path to `api/index.py`).
2. In the project: **Storage → Create Database → Neon (Postgres)** and connect it. This sets `DATABASE_URL`/`POSTGRES_URL` automatically. Add `VAPI_WEBHOOK_SECRET=<openssl rand -hex 24>` under **Settings → Environment Variables**, then redeploy.
3. Locally, set `VAPI_API_KEY` (Vapi dashboard → API Keys → private key), `PUBLIC_BASE_URL` (the Vercel URL) and the same `VAPI_WEBHOOK_SECRET` in `.env`, then run:
   ```bash
   python scripts/setup_vapi.py --buy-number 512   # creates the assistant and a free Vapi US number
   ```
   You can also create a free number in the Vapi dashboard (Phone Numbers → Create) and run `python scripts/setup_vapi.py --phone-number-id <id>`.
4. Call the number. Re-run the script after any prompt or tool change; it updates the assistant in place.

**Serverless notes.** On Vercel the app creates tables and seed data on the first request (startup hooks aren't guaranteed there), opens one DB connection per request instead of keeping a pool, and refuses to start without a database rather than falling back to a SQLite file that the platform would wipe.

**Container hosts instead.** `docker build .` produces a self-contained image (`$PORT` respected); `railway.json` is included for Railway. Point `DATABASE_URL` at any Postgres.

## Environment variables

| Variable | Used by | Required | Description |
|---|---|---|---|
| `DATABASE_URL` (or `POSTGRES_URL`) | app | prod | Postgres URL (`postgres://` accepted). Defaults to SQLite `./data/patients.db` locally; required on Vercel |
| `VAPI_WEBHOOK_SECRET` | app + setup | prod | Shared secret Vapi sends in `x-webhook-secret`; empty disables the check (local only) |
| `API_KEY` | app | no | If set, POST/PUT/DELETE need `X-API-Key` |
| `SEED_DATA` | app | no | Insert two demo patients into an empty DB (default `true`) |
| `CLINIC_NAME`, `CLINIC_TIMEZONE` | app + setup | no | Spoken clinic name; timezone for "today" and appointment slots |
| `LOG_LEVEL` | app | no | Default `INFO` |
| `VAPI_API_KEY` | setup | yes | Vapi private API key |
| `PUBLIC_BASE_URL` | setup | yes | Public HTTPS URL of the backend |
| `VAPI_ASSISTANT_ID`, `VAPI_PHONE_NUMBER_ID` | setup | no | Target a specific assistant/number |
| `VAPI_MODEL_PROVIDER`, `VAPI_MODEL` | setup | no | LLM (default `openai` / `gpt-4o`) |
| `VAPI_VOICE_*`, `VAPI_TRANSCRIBER_*` | setup | no | Voice and STT overrides |

## Trade-offs and known limitations

- **`create_all` instead of migrations.** Fine for a fresh schema; Alembic is the first thing to add before the schema changes.
- **Returning-caller lookup shares the name** of whoever owns that number (needed for the "we already have a record for…" prompt from the spec). In production I'd confirm DOB first, then reveal the name.
- **PHI in logs.** The spec asks for the payload to be logged. A real deployment would redact it or send it to an access-controlled sink. No HIPAA controls (per the FAQ).
- **Reads are unauthenticated** so reviewers can test easily. Writes can be locked with `API_KEY`.
- **Appointments are mock.** Availability is generated on the fly (weekdays 9–4, two providers); only bookings are stored.
- **One Vapi webhook and one LLM.** If Vapi or OpenAI has an outage, the line is down; there's no fallback assistant.
- **Partial data isn't saved when a call drops.** I chose this to keep unconfirmed data out of the patient table; the transcript is kept so staff can follow up.
- **The STT `multi` language mode** is slightly less accurate on English-only calls than `en`. Set `VAPI_TRANSCRIBER_LANGUAGE=en` if Spanish isn't needed.

## Next steps

- Alembic migrations, plus a partial unique index to stop exact-duplicate registrations (same name, DOB and phone).
- Store a cleaned, structured transcript (`artifact.messages`) instead of raw text, and attach recordings.
- Load-test the webhook and add a Vapi fallback model.
- SMS confirmation of the appointment via Vapi/Twilio.
- Authentication and roles on the dashboard; field-level encryption for PHI.
