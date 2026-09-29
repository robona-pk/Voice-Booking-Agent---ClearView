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

## How it's built

| Layer | Tech |
|---|---|
| LLM | Qwen 2.5 (3B), run locally with Ollama |
| Agent server | FastAPI with tool calling |
| Business backend | FastAPI + SQLite (pincodes, slots, bookings, waitlist, funnel events) |
| Voice | Browser speech recognition and synthesis (Chrome) |
| Interface | Phone-style web page |

## Product decisions worth noting

- **Guardrails in code, not just the prompt.** The small model kept skipping steps: it jumped to the waitlist for serviceable pincodes and invented a pincode nobody had spoken. I fixed this by tracking conversation state in code, rejecting tool calls that don't match it, and injecting the current state into every turn. This is deterministic rules around a probabilistic model.
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

## What's next

- Funnel analytics dashboard
- Hinglish support
- Pipecat + Whisper for a fully open-source voice pipeline
- WhatsApp/SMS confirmations and reminder calls to reduce no-shows

## About

Built by Prerna Kapoor
