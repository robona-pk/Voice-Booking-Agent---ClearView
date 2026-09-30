"""ClearView's booking flow is state-machine controlled, not prompt controlled."""
import json
import os
import re
import uuid
from difflib import get_close_matches
from datetime import date, timedelta

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend import main as business

LLM = os.getenv("LLM_ENDPOINT", "http://localhost:11434/v1/chat/completions")
MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b-instruct")
LLM_API_KEY = os.getenv("LLM_API_KEY")
app = FastAPI()
# Keep the business endpoints available for inspection under one public app.
app.mount("/api", business.app)
sessions = {}


def digits(value):
    return re.sub(r"\D", "", str(value))


def log(call_id, step):
    """Call the business layer in-process so the deployed app has no localhost dependency."""
    try:
        business.event(business.Event(call_id=call_id, step=step))
    except Exception:
        pass


def parse_date(text):
    text = text.lower().strip()
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if match:
        return match.group(1)
    if text == "today":
        return date.today().isoformat()
    if text == "tomorrow":
        return (date.today() + timedelta(days=1)).isoformat()
    months = {"january": 1, "february": 2, "march": 3, "april": 4,
              "may": 5, "june": 6, "july": 7, "august": 8,
              "september": 9, "october": 10, "november": 11, "december": 12}
    # Speech recognition commonly produces near-miss month names such as
    # "ocotber". Correct only a close match to one of the twelve months.
    words = re.findall(r"[a-z]+", text)
    for word in words:
        if len(word) < 3:
            continue
        match = get_close_matches(word, months.keys(), n=1, cutoff=0.78)
        if match and word != match[0]:
            text = re.sub(rf"\b{re.escape(word)}\b", match[0], text)
    # Accept ordinary spoken formats: "1st October", "October 2nd", and
    # optional years. This parser is a reliable fallback to the LLM extractor.
    patterns = [
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(months) + r")(?:\s*,?\s*(\d{4}))?\b",
        r"\b(" + "|".join(months) + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?\b",
    ]
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text)
        if not match:
            continue
        if index == 0:
            day, month_name, year = int(match.group(1)), match.group(2), match.group(3)
        else:
            month_name, day, year = match.group(1), int(match.group(2)), match.group(3)
        year = int(year) if year else date.today().year
        try:
            parsed = date(year, months[month_name], day)
            if not match.group(3) and parsed < date.today():
                parsed = date(year + 1, months[month_name], day)
            return parsed.isoformat()
        except ValueError:
            return None
    days = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6}
    for label, weekday in days.items():
        if label in text:
            offset = (weekday - date.today().weekday()) % 7
            return (date.today() + timedelta(days=offset or 7 if "next" in text else offset)).isoformat()
    return None


def normalize_spoken_time(text):
    """Turn spoken times such as '2 pm' into the slot format '14:00'."""
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text.lower())
    if not match:
        return None
    hour, minute, period = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    if period == "pm" and hour != 12:
        hour += 12
    if period == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def interpret(field, text):
    """Use Qwen only to normalize the current answer, never to choose the next step.

    This makes natural answers such as "Friday" or a spoken address easier to
    process, while the state machine still validates all values and controls all
    customer-facing questions.
    """
    # Vercel cannot run a local Ollama daemon. It keeps the deterministic flow
    # working with raw input unless a hosted compatible LLM_ENDPOINT is supplied.
    if os.getenv("VERCEL") and "LLM_ENDPOINT" not in os.environ:
        return text
    prompt = (
        "Extract only the value for the requested field from a caller's answer. "
        "Return JSON only, in the form {\"value\": \"...\"}. Do not ask a question, "
        "do not add an explanation, and do not infer values that were not said. "
        f"Requested field: {field}. Caller answer: {text!r}"
    )
    result = model_json("You are a strict field extractor.", prompt, 60)
    return result.get("value", text).strip() if isinstance(result.get("value", text), str) else text


def model_json(system, prompt, max_tokens=100):
    """Ask the configured model for a constrained JSON decision, with a safe fallback."""
    if os.getenv("VERCEL") and "LLM_ENDPOINT" not in os.environ:
        return {}
    try:
        headers = {"Authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else {}
        response = httpx.post(LLM, headers=headers, json={"model": MODEL, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ], "max_tokens": max_tokens, "temperature": 0}, timeout=20).json()
        content = response["choices"][0]["message"].get("content", "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
        return json.loads(content)
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return {}


def slot_intent(text, slots):
    """Use the LLM for semantic interpretation of availability, not keyword matching."""
    offered = [slot["time"] for slot in slots]
    prompt = (
        "The customer is choosing from these appointment times: " + json.dumps(offered) + ". "
        "Classify their reply as exactly one intent: select_slot, needs_another_date, or unclear. "
        "Use needs_another_date for any meaning that they cannot attend the offered times, even if they do not say those exact words. "
        "If selecting a listed slot, set time to that exact HH:MM value; otherwise use null. "
        "Return JSON only: {\"intent\": \"...\", \"time\": \"HH:MM or null\"}. "
        f"Customer reply: {text!r}"
    )
    result = model_json("You classify appointment-selection intent. Never invent a slot.", prompt)
    return result if isinstance(result, dict) else {}


def confirmation_intent(text):
    """Interpret approval naturally, while booking itself remains code-controlled."""
    prompt = (
        "Classify this response to an appointment booking summary as exactly one of: "
        "confirm, change, or unclear. Treat ordinary approval, including 'ok', 'okay', "
        "'ook', 'go ahead', and 'please proceed', as confirm. Return JSON only: "
        "{\"intent\": \"confirm|change|unclear\"}. "
        f"Customer reply: {text!r}"
    )
    result = model_json("You classify booking-confirmation intent.", prompt, 40)
    return result.get("intent") if isinstance(result, dict) else None


class Session:
    QUESTIONS = {
        "service": "Would you like a home eye test or a frame trial?",
        "pincode": "What is your 6-digit pincode?",
        "address": "Please share your house or flat number and a nearby landmark.",
        "date": "Which date would you prefer? Please say today, tomorrow, or a weekday.",
        "name": "May I have your name?",
        "phone": "What is your 10-digit mobile number?",
        "waitlist_name": "May I have your name for the waitlist?",
        "waitlist_phone": "What is your 10-digit mobile number?",
        "waitlist_offer": "Would you like to join the waitlist?",
        "confirm": "Shall I confirm this appointment?",
    }

    def __init__(self):
        self.call_id = uuid.uuid4().hex[:8]
        self.stage = "service"
        self.service = self.pincode = self.city = self.area = None
        self.address = self.booking_date = self.name = self.phone = self.time = None
        self.slots = []
        log(self.call_id, "call_started")

    def ask(self):
        return self.QUESTIONS[self.stage].format(pincode=self.pincode)

    def offer_slots(self):
        result = business.slots(pincode=self.pincode, date=self.booking_date)
        self.slots = result.get("slots", [])
        log(self.call_id, "slots_offered")
        if not self.slots:
            self.stage = "date"
            return "I do not have a slot on that date. Which other date would you prefer?"
        self.stage = "slot"
        return self.slot_prompt()

    def slot_prompt(self):
        return "I have " + ", ".join(slot["time"] for slot in self.slots) + ". Which one would you prefer?"

    def reset_from(self, field):
        """Rewind only the details made invalid by an explicit correction."""
        if field == "pincode":
            self.pincode = self.city = self.area = self.address = self.booking_date = self.time = None
            self.slots, self.stage = [], "pincode"
        elif field == "address":
            self.address = self.booking_date = self.time = None
            self.slots, self.stage = [], "address"
        elif field == "date":
            self.booking_date = self.time = None
            self.slots, self.stage = [], "date"
        elif field == "slot":
            self.time, self.stage = None, "slot"
            return "Sure. " + self.slot_prompt()
        return "Sure. " + self.ask()

    def book(self):
        payload = {"call_id": self.call_id, "name": self.name, "phone": self.phone,
                   "service": self.service, "pincode": self.pincode, "address": self.address,
                   "date": self.booking_date, "time": self.time}
        result = business.book(business.Booking(**payload))
        if result.get("success"):
            log(self.call_id, "booked")
            self.stage = "complete"
            return f"Your appointment is confirmed. Your booking ID is {result['booking_id']}. Thank you for calling ClearView."
        self.stage = "date"
        return "That slot was just taken. Which other date would you prefer?"

    def waitlist(self):
        business.waitlist(business.Waitlist(name=self.name, phone=self.phone, pincode=self.pincode))
        log(self.call_id, "waitlisted")
        self.stage = "complete"
        return "You are on our waitlist. A team member will contact you when service reaches your area. Thank you."

    def reply(self, raw):
        """Capture one field and ask one fixed next question: no bundled prompts."""
        text = raw.strip()
        lower = text.lower()
        if any(word in lower for word in ("human", "representative", "agent")):
            self.stage = "complete"
            return "A team member will call you back. Thank you for calling ClearView."
        if self.stage == "complete":
            return "This call has ended. Please start a new call if you need help."
        if any(word in lower for word in ("change", "update", "edit", "different")):
            if "pincode" in lower or "pin code" in lower:
                return self.reset_from("pincode")
            if "address" in lower or "flat" in lower or "house" in lower:
                return self.reset_from("address")
            if "date" in lower or "day" in lower:
                return self.reset_from("date")
            if "slot" in lower or "time" in lower:
                return self.reset_from("slot")
        if self.stage == "service":
            text = interpret("service: home eye test or frame trial", text)
            lower = text.lower()
            if "frame" in lower or "trial" in lower:
                self.service = "frame trial"
            elif "eye" in lower or "test" in lower or "checkup" in lower:
                self.service = "home eye test"
            else:
                return self.ask()
            self.stage = "pincode"
            return self.ask()
        if self.stage == "pincode":
            candidate = digits(text)
            if len(candidate) != 6:
                return "I need a 6-digit pincode. Please say it one digit at a time."
            self.pincode = candidate
            try:
                result = business.serviceability(self.pincode)
            except Exception:
                return "I cannot check serviceability right now. Please try again shortly."
            log(self.call_id, "pincode_captured")
            if result.get("serviceable"):
                self.city, self.area, self.stage = result["city"], result["area"], "address"
                log(self.call_id, "serviceable")
                return f"Yes, we serve {self.area}, {self.city}. {self.ask()}"
            self.stage = "waitlist_offer"
            return "Sorry, we do not serve that area yet. " + self.ask()
        if self.stage == "address":
            text = interpret("house or flat number and landmark", text)
            if len(text) < 5:
                return self.ask()
            self.address, self.stage = text, "date"
            return self.ask()
        if self.stage == "date":
            # Use the raw phrase too, because an LLM extractor may return a
            # non-date string even when the caller said a valid calendar date.
            parsed = parse_date(interpret("preferred appointment date", text)) or parse_date(text)
            if not parsed:
                return "Please say a date such as 1st October, tomorrow, a weekday, or YYYY-MM-DD."
            self.booking_date = parsed
            try:
                return self.offer_slots()
            except Exception:
                return "I cannot check slots right now. Please try again shortly."
        if self.stage == "waitlist_offer":
            if lower in {"yes", "yeah", "yep", "sure", "okay", "ok"}:
                self.stage = "waitlist_name"
                return self.ask()
            if lower in {"no", "nope", "not now"}:
                self.stage = "complete"
                return "No problem. Thank you for calling ClearView."
            return self.ask()
        if self.stage == "slot":
            compact = lower.replace(" ", "")
            semantic = slot_intent(text, self.slots)
            semantic_time = semantic.get("time") if semantic.get("intent") == "select_slot" else None
            self.time = next((s["time"] for s in self.slots if s["time"] == semantic_time), None)
            # The short fallback still works when a hosted model is unavailable.
            spoken_time = normalize_spoken_time(text)
            self.time = self.time or next((s["time"] for s in self.slots if s["time"] == spoken_time), None)
            self.time = self.time or next((s["time"] for s in self.slots if s["time"] in text or s["time"].split(":")[0] + "pm" in compact or s["time"].split(":")[0] + "am" in compact), None)
            if not self.time:
                if semantic.get("intent") == "needs_another_date":
                    self.stage = "date"
                    return "I understand. Those are the only slots I have that day. Which other date would work for you?"
                unable = ("not available", "not free", "can't", "cannot", "won't work", "why", "different day", "another day")
                if any(phrase in lower for phrase in unable):
                    self.stage = "date"
                    return "I understand. Those are the only slots I have that day. Which other date would work for you?"
                requested_time = re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", lower)
                if requested_time:
                    self.stage = "date"
                    return f"I do not have {requested_time.group(0)} that day. Which other date would work for you?"
                return "You can choose one of those times, or say that you need a different date."
            self.stage = "name"
            return self.ask()
        if self.stage in {"name", "waitlist_name"}:
            text = interpret("customer name", text)
            if len(text) < 2 or digits(text) == text:
                return self.ask()
            self.name = text
            self.stage = "phone" if self.stage == "name" else "waitlist_phone"
            return self.ask()
        if self.stage in {"phone", "waitlist_phone"}:
            self.phone = digits(text)
            if len(self.phone) != 10:
                return "I need a 10-digit mobile number. Please say it again."
            if self.stage == "waitlist_phone":
                try:
                    return self.waitlist()
                except Exception:
                    return "I cannot save the waitlist request right now. Please try again shortly."
            self.stage = "confirm"
            return (f"To confirm: {self.service} at {self.address}, {self.area}, {self.city}, on {self.booking_date} at {self.time}, for {self.name}. "
                    "Say confirm, or say change address, pincode, date, or slot.")
        if self.stage == "confirm":
            semantic = confirmation_intent(text)
            approved = {"yes", "yeah", "yep", "confirm", "correct", "ok", "okay", "ook", "go ahead", "please proceed"}
            if semantic == "confirm" or lower in approved:
                try:
                    return self.book()
                except Exception:
                    return "I could not complete the booking. Shall I try again?"
            if semantic == "change" or lower in {"no", "nope", "change"}:
                self.stage = "date"
                return "No problem. Which date would you prefer instead?"
            return self.ask()
        return self.ask()


class ChatIn(BaseModel):
    session_id: str
    text: str


@app.post("/start")
def start():
    session = Session()
    sessions[session.call_id] = session
    greeting = "Hi, this is Charlie from ClearView At-Home. This is an AI demo call and may be recorded. "
    return {"session_id": session.call_id, "reply": greeting + session.ask()}


@app.post("/chat")
def chat(payload: ChatIn):
    session = sessions.get(payload.session_id)
    return {"reply": session.reply(payload.text) if session else "This call has ended. Please start a new one."}


@app.get("/")
def index():
    return FileResponse("agent/index.html")


@app.get("/phone")
def phone():
    return FileResponse("agent/phone.html")
