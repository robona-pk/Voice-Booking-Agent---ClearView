# Charlie: AI Voice Booking Agent for Home Services

A voice AI agent that books home appointments (demo: home eye test / frame trial) over a phone-style call. It collects a pincode, checks serviceability, takes the address, offers slots and books the appointment.

> Fictional brand ("ClearView At-Home") built as a product experiment. Inspired by home-visit booking flows at companies like Lenskart, Tata 1mg and Urban Company. Not affiliated with any of them. All data is mock data.

**Demo video:** [Watch the demo](https://drive.google.com/file/d/1v4zPdY0VOVt4T3fvCA_SYCRnVCR4elWL/view?usp=sharing)

## The problem

In-app booking funnels leak at address entry and slot selection. Many users (older customers, regional-language speakers, people who don't trust apps) would rather just call. A voice agent gives them a zero-friction path and helps the business capture bookings it would otherwise lose.

## What it does

1. Greets the caller and discloses it's an AI demo call
2. Asks which service they want
3. Collects a 6-digit pincode and checks serviceability
4. If the area isn't serviceable, adds the caller to a waitlist. This doubles as demand data for expansion.
5. Collects the address and preferred date
6. Offers up to 3 available slots
7. Confirms the details, books the appointment and returns a booking ID

## Documentation

- [Technology flowchart and responsibilities](docs/ARCHITECTURE.md)
- [Brief API reference](docs/API.md)

## How it's built

| Layer | Tech |
|---|---|
| LLM / NLU | Qwen 2.5 (3B) in Ollama; extracts the current expected answer only |
| Conversation control | Deterministic finite-state machine in FastAPI |
| Agent server | FastAPI session and validation layer |
| Business backend | FastAPI + SQLite (pincodes, slots, bookings, waitlist, funnel events) |
| Voice | Browser speech recognition and synthesis (Chrome) |
| Interface | Phone-style web page |

## Product decisions worth noting

- **The booking order lives in code.** A finite-state machine owns the conversation: service, pincode, confirmation, address, date, slot, name, phone and final confirmation. Charlie can collect only the current field and asks only one question at a time.
- **Input validation for voice.** Pincodes must be 6 digits, and spoken input like "560 034" is normalised before the lookup.
- **Funnel events logged at every step**, so drop-off can be measured.
- **Waitlist as a growth signal.** Requests from unserviceable pincodes show where to expand.
- **AI and recording disclosure** at the start of every call.

## Results and learnings

_Add your real numbers here: how many test calls, how many ended in a booking, what failed, typical response time._

## Known limitations

- Browser speech recognition is Chrome-only, and audio goes through Google's service, so the voice layer isn't fully open source.
- A 3B model on a laptop takes several seconds per turn. Fine for a demo, too slow for production.
- Digits and Hinglish are the weak spots for speech recognition.
- Demo only. It isn't connected to a real phone number.

## Run it locally

Requires Python 3.10+ and [Ollama](https://ollama.com).

```bash
git clone https://github.com/robona-pk/charlie-voice-booking-agent.git
cd charlie-voice-booking-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull qwen2.5:3b-instruct
```

Start the backend once so it creates the database, stop it, then seed:

```bash
uvicorn backend.main:app --port 8000    # wait for "startup complete", then Ctrl+C
python backend/seed.py                  # run once
uvicorn backend.main:app --port 8000    # keep running
```

In a second terminal:

```bash
source .venv/bin/activate
uvicorn agent.server:app --port 8001
```

Open http://localhost:8001/phone in Chrome and press the green call button. Serviceable test pincodes: `560034`, `560001`, `110001`, `400001`, `122001`. Use `999999` to test the waitlist.

## Deploying to Vercel

`pyproject.toml` explicitly selects `agent.server:app` as the single FastAPI entrypoint. The business endpoints are mounted beneath `/api`, so Vercel does not need to discover two separate apps.

The Vercel demo uses SQLite in `/tmp`, which is temporary and can reset when a function is restarted. It is suitable for a demo, not real booking data. Local Ollama also cannot run on Vercel; set a hosted OpenAI-compatible `LLM_ENDPOINT` environment variable to use the optional answer-normalisation layer in deployment. The state-machine flow works without it.

For a hosted provider, set these Vercel environment variables (never prefix them with `NEXT_PUBLIC_`):

```text
LLM_ENDPOINT=https://<provider's OpenAI-compatible host>/v1/chat/completions
LLM_MODEL=<a small, current model ID from that provider>
LLM_API_KEY=<provider API key>
```

The model is used only to normalize the one expected caller answer. All booking order, validation, and API permissions remain in the server-side state machine.

## What's next

- Funnel analytics dashboard
- Hinglish support
- Pipecat + Whisper for a fully open-source voice pipeline
- WhatsApp/SMS confirmations and reminder calls to reduce no-shows

## About

Built by Prerna Kapoor
