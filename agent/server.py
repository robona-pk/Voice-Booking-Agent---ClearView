import json, re, uuid, traceback, httpx
from datetime import date
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

API = "http://localhost:8000"
LLM = "http://localhost:11434/v1/chat/completions"
MODEL = "qwen2.5:3b-instruct"

app = FastAPI()
sessions = {}

def build_system():
    today = date.today()
    return open("agent/prompt.md").read().replace(
        "{today}", f"{today.strftime('%A, %d %B %Y')} ({today.isoformat()})")

def log(call_id, step):
    httpx.post(f"{API}/event", json={"call_id": call_id, "step": step})

def digits(s):
    return re.sub(r"\D", "", str(s))

class Session:
    def __init__(self):
        self.call_id = uuid.uuid4().hex[:8]
        self.base_system = build_system()
        self.serviceable = {}      # pincode -> True/False (only after a real check)
        self.spoken = []           # digits from each thing the caller said
        self.last_pin = None
        self.city = None
        self.service = None
        self.messages = [{"role": "system", "content": self.base_system},
                         {"role": "user", "content": "(call connected)"}]
        log(self.call_id, "call_started")

    def state_hint(self):
        if self.service is None:
            return ("The caller has NOT chosen a service yet. Do NOT call any tool. "
                    "Ask only: 'Would you like a home eye test or a frame trial?'")
        if self.last_pin is None:
            return (f"Service chosen: {self.service}. No pincode collected yet. Do NOT call any tool "
                    "until the caller says a 6-digit pincode. Ask: 'What is your 6-digit pincode?'")
        if self.serviceable.get(self.last_pin):
            return (f"Service: {self.service}. Pincode {self.last_pin} ({self.city}) is serviceable. "
                    "Never use join_waitlist. Collect in order: address, preferred date "
                    "(then call get_slots), name and phone, then confirm and call book_appointment.")
        return (f"Pincode {self.last_pin} is NOT serviceable. Apologise, offer the waitlist, "
                "collect name and phone, then call join_waitlist.")

    def check_serviceability(self, pincode):
        pincode = digits(pincode)
        if len(pincode) != 6:
            return {"error": "Pincode must be exactly 6 digits. Ask the caller for their pincode."}
        if not any(pincode in d for d in self.spoken):
            return {"error": "The caller has NOT given this pincode. Do not guess. Ask: 'What is your 6-digit pincode?'"}
        r = httpx.get(f"{API}/serviceability/{pincode}").json()
        self.serviceable[pincode] = bool(r.get("serviceable"))
        self.last_pin = pincode
        self.city = r.get("city")
        log(self.call_id, "pincode_captured")
        if r.get("serviceable"):
            log(self.call_id, "serviceable")
            r["next_step"] = "Serviceable. Do NOT use the waitlist. Ask for house/flat number and landmark, then the preferred date."
        else:
            r["next_step"] = "Not serviceable. Apologise and offer the waitlist."
        return r

    def get_slots(self, pincode, date):
        pincode = digits(pincode)
        if not self.serviceable.get(pincode):
            return {"error": "Pincode has not been checked as serviceable. Ask for the pincode first."}
        r = httpx.get(f"{API}/slots", params={"pincode": pincode, "date": date}).json()
        log(self.call_id, "slots_offered")
        return r

    def book_appointment(self, **kw):
        kw["pincode"] = digits(kw.get("pincode", ""))
        if not self.serviceable.get(kw["pincode"]):
            return {"error": "Pincode has not been checked as serviceable. Ask for the pincode first."}
        r = httpx.post(f"{API}/book", json={**kw, "call_id": self.call_id}).json()
        if r.get("success"): log(self.call_id, "booked")
        return r

    def join_waitlist(self, **kw):
        kw["pincode"] = digits(kw.get("pincode", ""))
        if self.serviceable.get(kw["pincode"]) is not False:
            return {"error": "Only waitlist a pincode that was checked and found NOT serviceable. Do not waitlist now."}
        r = httpx.post(f"{API}/waitlist", json=kw).json()
        log(self.call_id, "waitlisted")
        return r

def fn(name, desc, props):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": {k: {"type": "string"} for k in props},
                           "required": props}}}

SCHEMAS = [
    fn("check_serviceability", "Check a 6-digit pincode the caller has actually spoken. Never guess a pincode.", ["pincode"]),
    fn("get_slots", "Get available slots for a serviceable pincode and date (YYYY-MM-DD)", ["pincode", "date"]),
    fn("book_appointment", "Book the appointment after the caller confirms",
       ["name", "phone", "service", "pincode", "address", "date", "time"]),
    fn("join_waitlist", "Add caller to waitlist ONLY if the pincode was checked and is not serviceable", ["name", "phone", "pincode"]),
]

def agent_turn(s):
    for _ in range(6):
        s.messages[0]["content"] = s.base_system + "\n\nCURRENT STATE: " + s.state_hint()
        r = httpx.post(LLM, timeout=180, json={"model": MODEL, "messages": s.messages,
                       "tools": SCHEMAS, "max_tokens": 150}).json()
        msg = r["choices"][0]["message"]
        s.messages.append(msg)
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"])
                print(f"[tool] {name}({args})")
                try:
                    result = getattr(s, name)(**args)
                except Exception as e:
                    result = {"error": f"Tool call failed: {e}. Check the arguments and try again."}
                print(f"[result] {result}")
                s.messages.append({"role": "tool", "tool_call_id": tc["id"],
                                   "content": json.dumps(result)})
            continue
        return msg["content"] or "Sorry, could you say that again?"
    return "Sorry, could you repeat that?"

class ChatIn(BaseModel):
    session_id: str
    text: str

@app.post("/start")
def start():
    s = Session()
    sessions[s.call_id] = s
    return {"session_id": s.call_id, "reply": agent_turn(s)}

@app.post("/chat")
def chat(c: ChatIn):
    s = sessions.get(c.session_id)
    if not s:
        return {"reply": "This call has ended. Please start a new one."}
    s.spoken.append(digits(c.text))
    t = c.text.lower()
    if s.service is None:
        if "frame" in t or "trial" in t:
            s.service = "frame trial"
        elif "eye" in t or "test" in t or "checkup" in t:
            s.service = "home eye test"
    s.messages.append({"role": "user", "content": c.text})
    try:
        return {"reply": agent_turn(s)}
    except Exception:
        traceback.print_exc()
        return {"reply": "Sorry, I had a technical glitch. Could you repeat that?"}

@app.get("/")
def index():
    return FileResponse("agent/index.html")

@app.get("/phone")
def phone():
    return FileResponse("agent/phone.html")
